"""
Module 1 — Discovery Orchestrator
Coordinates query generation, web search, URL classification, download, and validation.
Returns a list of validated DiscoveredDocument models.
"""
import logging
import asyncio
from functools import partial
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.events import emit_event
from app.models.discovered_document import DiscoveredDocument, SourceType, EnforcementStatus
from app.modules.discovery.document_downloader import download_document, compute_content_hash
from app.modules.discovery.language_processor import process_document_language
from app.modules.discovery.query_generator import generate_queries
from app.modules.discovery.url_classifier import classify_url
from app.modules.discovery.web_searcher import search_queries
from app.modules.discovery.zone1_validator import run_zone1_validation

logger = logging.getLogger(__name__)


async def run_discovery(
    country: str,
    indicator_ids: list[str],
    run_id: str,
    pdf_url: Optional[str],
    db: AsyncSession,
) -> list[DiscoveredDocument]:
    """
    Execute the full Module 1 document discovery pipeline.
    
    Args:
        country: The target country.
        indicator_ids: List of RDTII indicator IDs to search for.
        run_id: The UUID of the current analysis run.
        pdf_url: Optional direct PDF link provided by the user.
        db: SQLAlchemy async session for persistence.
        
    Returns:
        List of persisted DiscoveredDocument models that passed Zone 1 checks.
    """
    discovered_docs: list[DiscoveredDocument] = []
    processed_urls: dict[str, DiscoveredDocument] = {}
    seen_acts: set[tuple[str, str]] = set()  # (canonical_act_key, indicator_id) for dedup

    # 1. Handle optional direct PDF upload
    if pdf_url:
        logger.info(f"[{run_id}] Processing user-provided PDF: {pdf_url}")
        doc = await _process_single_url(
            url=pdf_url,
            country=country,
            indicator_id="USER_PROVIDED",
            run_id=run_id,
            query_used="USER_PROVIDED",
            force_primary=True,
            db=db
        )
        processed_urls[pdf_url] = doc
        if doc.zone1_passed:
            discovered_docs.append(doc)

    # 2. Iterate through each requested indicator
    for ind_id in indicator_ids:
        logger.info(f"[{run_id}] Generating queries for indicator {ind_id}")
        
        # Step A: Generate queries
        try:
            queries = generate_queries(country, ind_id)
            emit_event(run_id, "SEARCH_QUERY", f"Generated {len(queries)} queries for {ind_id}",
                       agent="discovery", indicator_id=ind_id)
        except Exception as e:
            logger.error(f"[{run_id}] Failed to generate queries for {ind_id}: {e}")
            emit_event(run_id, "ERROR", f"Query generation failed for {ind_id}: {e}",
                       agent="discovery", indicator_id=ind_id)
            continue

        # Step B: Search Web (with country relevance filtering)
        search_fn = partial(
            search_queries, country, queries,
            settings.max_search_results_per_query, 2,
        )
        search_results = await asyncio.get_running_loop().run_in_executor(
            None, search_fn,
        )

        emit_event(run_id, "SEARCH_RESULT", f"Found {len(search_results)} unique URLs for {ind_id}",
                   agent="discovery", indicator_id=ind_id,
                   data={"total_results": len(search_results)})
        
        # Step C: Process results
        for sr in search_results:
            if sr.url in processed_urls:
                prev_doc = processed_urls[sr.url]
                new_doc = DiscoveredDocument(
                    run_id=prev_doc.run_id,
                    url=prev_doc.url,
                    title=prev_doc.title,
                    indicator_id=ind_id,
                    search_query_used=sr.query_used,
                    source_type=prev_doc.source_type,
                    enforcement_status=prev_doc.enforcement_status,
                    zone1_passed=prev_doc.zone1_passed,
                    original_content=prev_doc.original_content,
                    translated_content=prev_doc.translated_content,
                    content_hash=prev_doc.content_hash,
                    language=prev_doc.language,
                    download_status=prev_doc.download_status,
                    error_message=prev_doc.error_message,
                    ocr_quality_cer=prev_doc.ocr_quality_cer,
                )
                db.add(new_doc)
                if new_doc.zone1_passed:
                    discovered_docs.append(new_doc)
                continue
            
            doc = await _process_single_url(
                url=sr.url,
                country=country,
                indicator_id=ind_id,
                run_id=run_id,
                query_used=sr.query_used,
                force_primary=False,
                db=db,
                seen_acts=seen_acts,
            )
            
            processed_urls[sr.url] = doc
            if doc.zone1_passed:
                discovered_docs.append(doc)
                act_key = _extract_act_key(doc.original_content or doc.translated_content or "")
                if act_key:
                    seen_acts.add((act_key, ind_id))
                
    # Commit all saved documents to DB
    await db.commit()
    return discovered_docs


async def _process_single_url(
    url: str,
    country: str,
    indicator_id: str,
    run_id: str,
    query_used: str,
    force_primary: bool,
    db: AsyncSession,
    seen_acts: set | None = None,
) -> DiscoveredDocument:
    """Process a single URL through classification, download, and Zone 1 validation."""
    
    # 1. Classify URL
    if force_primary:
        source_type = SourceType.PRIMARY_HIGH
    else:
        source_type = classify_url(url, country, indicator_id)

    emit_event(run_id, "CLASSIFY", f"Classified as {source_type.name}: {url[:100]}",
               agent="discovery", indicator_id=indicator_id,
               data={"source_type": source_type.name, "url": url})
        
    # Download PRIMARY sources first; also download SECONDARY_LEAD as fallback
    # because in restricted environments (Docker, CI) primary .gov portals are often
    # blocked or rate-limited, and secondary sources (law firm summaries, UNCTAD pages)
    # may be the only content available to anchor the analysis.
    DOWNLOADABLE = {
        SourceType.PRIMARY_HIGH,
        SourceType.PRIMARY_MEDIUM,
        SourceType.PRIMARY_GAZETTE,
        SourceType.SECONDARY_APPROVED,
        SourceType.SECONDARY_LEAD,  # include secondary leads — better than zero docs
    }
    if source_type not in DOWNLOADABLE:
        logger.debug(f"[Discovery] Skipping {source_type.name}: {url}")

        # Still record excluded URLs in the DB so they appear in audit logs
        doc = DiscoveredDocument(
            run_id=run_id,
            url=url,
            indicator_id=indicator_id,
            search_query_used=query_used,
            source_type=source_type,
            download_status="SKIPPED",
            zone1_passed=False
        )
        db.add(doc)
        return doc

    # 2. Download
    logger.info(f"[Discovery] Downloading {source_type.name}: {url}")
    emit_event(run_id, "DOWNLOAD", f"Downloading {source_type.name}: {url[:100]}",
               agent="discovery", indicator_id=indicator_id, data={"url": url})
    raw_text, error, ocr_cer = await download_document(url)
    
    if not raw_text or error:
        emit_event(run_id, "DOWNLOAD_FAILED", f"Failed to download: {url[:100]} — {error}",
                   agent="discovery", indicator_id=indicator_id, data={"url": url, "error": error})
        doc = DiscoveredDocument(
            run_id=run_id,
            url=url,
            indicator_id=indicator_id,
            search_query_used=query_used,
            source_type=source_type,
            download_status="FAILED",
            error_message=error,
            ocr_quality_cer=ocr_cer or 0.0,
            zone1_passed=False
        )
        db.add(doc)
        return doc
        
    content_hash = compute_content_hash(raw_text)
    emit_event(run_id, "DOWNLOAD_SUCCESS", f"Downloaded {len(raw_text)} chars from {url[:80]} (cer={ocr_cer})",
               agent="discovery", indicator_id=indicator_id,
               data={"url": url, "size": len(raw_text), "ocr_cer": ocr_cer})
    
    # 3. Language Processing
    lang, orig_text, trans_text = process_document_language(raw_text)
    orig_text = _sanitize_text(orig_text) or ""
    trans_text = _sanitize_text(trans_text)
    final_text = trans_text if trans_text else orig_text
    
    # 4. Zone 1 Validation
    zone1_passed, enforcement_status = run_zone1_validation(final_text)
    
    # Override source type if it's draft/repealed
    if not zone1_passed:
        source_type = SourceType.EXCLUDED

    emit_event(run_id, "ZONE1", f"Zone1={'PASS' if zone1_passed else 'FAIL'} ({enforcement_status.name}): {url[:80]}",
               agent="discovery", indicator_id=indicator_id,
               data={"zone1_passed": zone1_passed, "enforcement_status": enforcement_status.name})

    # Dedup: skip if same act name already seen for this indicator
    act_key = _extract_act_key(orig_text or trans_text or "")
    if act_key and seen_acts is not None and (act_key, indicator_id) in seen_acts:
        logger.info(f"[Discovery] Skipping duplicate act '{act_key}' for {indicator_id}: {url[:80]}")
        doc = DiscoveredDocument(
            run_id=run_id,
            url=url,
            indicator_id=indicator_id,
            search_query_used=query_used,
            source_type=source_type,
            enforcement_status=enforcement_status,
            zone1_passed=False,
            original_content="",
            translated_content="",
            content_hash="",
            language="en",
            download_status="SKIPPED",
            error_message=f"Duplicate act: {act_key}"
        )
        db.add(doc)
        return doc

    # 5. Save to DB
    doc = DiscoveredDocument(
        run_id=run_id,
        url=url,
        indicator_id=indicator_id,
        search_query_used=query_used,
        source_type=source_type,
        enforcement_status=enforcement_status,
        zone1_passed=zone1_passed,
        original_content=orig_text,
        translated_content=trans_text,
        content_hash=content_hash,
        language=lang,
        ocr_quality_cer=ocr_cer or 0.0,
        download_status="SUCCESS"
    )
    db.add(doc)
    
    return doc


def _sanitize_text(text: str | None) -> str | None:
    """Strip null bytes that PostgreSQL UTF8 encoding rejects."""
    if text is None:
        return None
    return text.replace("\x00", "")


def _extract_act_key(text: str) -> str:
    """Extract canonical act name from document text for deduplication.
    E.g. 'Privacy Act 1988 - Federal Register...' → 'privacy act 1988'
    Uses earliest match in text so the document's own title (top of page)
    wins over cross-references in the body."""
    import re
    pat = re.compile(
        r"(?i)((?:[A-Z][a-z]+(?:-[A-Z][a-z]+)*"
        r"(?:\s+(?:[A-Z][a-z]+(?:-[A-Z][a-z]+)*"
        r"|\([A-Z][A-Za-z0-9 /.,\'\-]+\)"
        r"|of|the|and|for|in|on|to|by|at|or|an|as))*)"
        r"\s+(?:Act|Regulation|Code|Order|Rule|Directive|Standard"
        r"|Policy|Decree|Ordinance|Statute|Convention|Treaty"
        r"|Protocol|Framework|Agreement|Law)s?"
        r"(?:\s+\(?[12]\d{3}\)?)?"
        r"(?:\s*\([A-Za-z0-9 /.,\'-]+\))?)",
    )
    best = None
    best_pos = float('inf')
    for m in pat.finditer(text[:2000]):
        pos = m.start()
        if pos < best_pos:
            best_pos = pos
            best = m.group(1)
    if best:
        return best.strip().lower()
    # Fallback: just take first line
    first_line = text.split("\n")[0].strip().lower()[:60]
    return first_line if first_line else ""

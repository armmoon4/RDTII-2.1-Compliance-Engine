"""
Module 2 — Analysis Orchestrator
Coordinates the full per-indicator analysis pipeline:
  1. Collect all discovered document text chunks, grouped by indicator
  2. Embed chunks into ChromaDB (per run)
  3. For each indicator: retrieve only its own chunks → run 3-agent pipeline
  4. Validate LLM output against actual source content to prevent hallucination
  5. Return list of raw result dicts ready for Module 3 persistence

Uses a simple sequential LangGraph-style pipeline (Prosecution → Defense → Arbiter).
"""
import asyncio
import logging
import re
from typing import Any

from app.config import settings
from app.events import emit_event
from app.modules.analysis.agents.arbiter_agent import run_arbiter
from app.modules.analysis.agents.defense_agent import run_defense
from app.modules.analysis.agents.prosecution_agent import run_prosecution
from app.modules.analysis.agents.state import AnalysisState
from app.modules.analysis.document_chunker import chunk_document
from app.modules.analysis.embeddings import cleanup_collection, embed_and_store, retrieve_top_k
from app.modules.analysis.indicator_mapper import enforce_indicator_rules
from app.modules.analysis.knowledge_graph import LegalKnowledgeGraph
from app.modules.analysis.legal_system_classifier import classify_legal_system
from app.modules.analysis.scoring_engine import VALID_SCORES
from app.modules.discovery.query_generator import INDICATOR_QUESTION_BANK

# Pillars that share chunk pools during fallback — a document discovered for
# any indicator in a related pillar becomes available to all sibling indicators.
# This avoids the need to hardcode law names or country-specific search terms.
PILLAR_RELATIONS: dict[str, list[str]] = {
    "6": ["7"],  # Pillar 6 (cross-border data) reuses Pillar 7 (data privacy) chunks
    "7": ["6"],  # And vice versa — same laws are relevant to both
}

logger = logging.getLogger(__name__)


async def run_analysis(
    discovered_docs: list,
    country: str,
    indicator_ids: list[str],
    run_id: str,
    db: Any = None,
    run: Any = None,
    has_provided_pdf: bool = False,
) -> list[dict[str, Any]]:
    """
    Execute Module 2: Multi-Agent Adversarial Analysis.

    Chunks are grouped by indicator_id so that each indicator only sees documents
    discovered FOR it — preventing cross-contamination that leads to hallucinated references.
    """
    logger.info(f"[Analysis] Starting for {country}, {len(discovered_docs)} docs, "
                f"{len(indicator_ids)} indicators.")

    legal_system = classify_legal_system(country)
    logger.info(f"[Analysis] {country} legal system: {legal_system}")

    # ── Step 2: Chunk documents, grouped by indicator_id ─────────────────
    _MAX_CHUNKS_PER_DOC = 200
    indicator_chunks: dict[str, list[dict]] = {}
    pillar_chunks: dict[str, list[dict]] = {}
    for doc in discovered_docs:
        text = doc.translated_content or doc.original_content
        if not text:
            continue
        ind_id = doc.indicator_id or "UNKNOWN"
        doc_chunks = chunk_document(text, source_url=doc.url, doc_id=doc.id, indicator_id=ind_id)
        if len(doc_chunks) > _MAX_CHUNKS_PER_DOC:
            keep = _MAX_CHUNKS_PER_DOC
            n = len(doc_chunks)
            mid = n // 2
            half = keep // 2
            head = doc_chunks[:half]
            tail = doc_chunks[-half:] if half > 0 else []
            doc_chunks = head + tail
            logger.info(f"[Analysis] Truncated doc {doc.id}: {n} → {len(doc_chunks)} chunks "
                        f"(kept first {half} + last {half})")
        indicator_chunks.setdefault(ind_id, []).extend(doc_chunks)
        pillar = ind_id.split(".")[0]
        pillar_chunks.setdefault(pillar, []).extend(doc_chunks)

    # Cross-pillar sharing: merge chunks from related pillars so that a document
    # discovered for (e.g.) 7.1 is also available to indicators in pillar 6.
    for pillar, related_pillars in PILLAR_RELATIONS.items():
        for rp in related_pillars:
            if rp in pillar_chunks:
                pillar_chunks.setdefault(pillar, []).extend(pillar_chunks[rp])

    all_chunks_flat = [c for clist in indicator_chunks.values() for c in clist]
    emit_event(run_id, "CHUNK", f"Chunked {len(discovered_docs)} docs into {len(all_chunks_flat)} chunks",
               agent="discovery", data={"doc_count": len(discovered_docs), "chunk_count": len(all_chunks_flat)})
    logger.info(f"[Analysis] Total chunks: {len(all_chunks_flat)}")

    # Cap total chunks to limit embedding time
    # Uses uniform sampling (proportional) instead of head+tail to preserve
    # representation from throughout each document.
    max_chunks = settings.max_total_chunks
    if len(all_chunks_flat) > max_chunks:
        logger.warning(f"[Analysis] Capping {len(all_chunks_flat)} chunks to {max_chunks} (uniform sampling)")
        all_chunks_flat = _uniform_sample(all_chunks_flat, max_chunks)
        for key in list(indicator_chunks.keys()):
            indicator_chunks[key] = _uniform_sample(indicator_chunks[key], max_chunks // 2)
        for key in list(pillar_chunks.keys()):
            pillar_chunks[key] = _uniform_sample(pillar_chunks[key], max_chunks)

    # ── Build legal knowledge graph for supersession tracking ──────────────
    kg = LegalKnowledgeGraph()
    for doc in discovered_docs:
        text = doc.translated_content or doc.original_content
        if text:
            kg.add_document(text, source_id=str(doc.id))
    kg_size = kg.graph.number_of_nodes()
    logger.info(f"[Analysis] Knowledge graph built: {kg_size} nodes, "
                f"{kg.graph.number_of_edges()} edges")

    embed_success = False
    if all_chunks_flat and len(all_chunks_flat) >= 5:
        embed_success = await asyncio.get_running_loop().run_in_executor(
            None, embed_and_store, all_chunks_flat, run_id)
        emit_event(run_id, "EMBED",
                   f"Embedded {len(all_chunks_flat)} chunks into vector DB" if embed_success else "Vector embedding failed",
                   agent="discovery", data={"chunk_count": len(all_chunks_flat), "success": embed_success})
        if not embed_success:
            logger.warning("[Analysis] ChromaDB embed failed — falling back to direct chunk search.")
    else:
        logger.info(f"[Analysis] Skipping vector embedding ({len(all_chunks_flat)} chunks < 5) — keyword search only.")

    # ── Step 3: Run 3-agent pipeline per indicator in parallel ──
    results: list[dict[str, Any]] = []
    _sem = asyncio.Semaphore(5)  # max 5 concurrent indicators

    import time as _time

    async def _run_one(indicator_id: str) -> list[dict[str, Any]]:
        """Analyse a single indicator with its own chunks, with retry on failure."""
        async with _sem:
            t0 = _time.time()
            this_indicator_chunks = indicator_chunks.get(indicator_id, [])
            try:
                rows = await _analyse_indicator(
                    indicator_id=indicator_id,
                    country=country,
                    run_id=run_id,
                    all_chunks=all_chunks_flat,
                    indicator_chunks=this_indicator_chunks,
                    pillar_chunks=pillar_chunks,
                    has_embeddings=embed_success,
                    has_provided_pdf=has_provided_pdf,
                    knowledge_graph=kg,
                )
                for r in rows:
                    r["processing_time"] = round(_time.time() - t0, 2)
                return rows
            except Exception as exc:
                logger.warning(f"[Analysis] Failed for {indicator_id}: {exc} — retrying once with pillar fallback...")
                emit_event(run_id, "INDICATOR_RETRY", f"{indicator_id} failed, retrying: {exc}",
                           agent="arbiter", indicator_id=indicator_id, data={"error": str(exc)})
                try:
                    pillar = indicator_id.split(".")[0]
                    retry_chunks = pillar_chunks.get(pillar, [])
                    if not retry_chunks:
                        retry_chunks = all_chunks_flat
                    retry_rows = await _analyse_indicator(
                        indicator_id=indicator_id,
                        country=country,
                        run_id=run_id,
                        all_chunks=all_chunks_flat,
                        indicator_chunks=retry_chunks,
                        pillar_chunks=pillar_chunks,
                        has_embeddings=embed_success,
                        has_provided_pdf=has_provided_pdf,
                        knowledge_graph=kg,
                    )
                    for retry_r in retry_rows:
                        retry_r["processing_time"] = round(_time.time() - t0, 2)
                        retry_r["note"] = (retry_r.get("note") or "") + " [Retried after initial failure]"
                    return retry_rows
                except Exception as retry_exc:
                    logger.exception(f"[Analysis] Retry also failed for {indicator_id}: {retry_exc}")
                    emit_event(run_id, "INDICATOR_FAILED", f"{indicator_id} failed after retry: {retry_exc}",
                               agent="arbiter", indicator_id=indicator_id, data={"error": str(retry_exc)})
                    return [_make_error_result(indicator_id, str(retry_exc))]

    tasks = [_run_one(indicator_id) for indicator_id in indicator_ids]
    all_result_rows = await asyncio.gather(*tasks)
    for idx, rows in enumerate(all_result_rows):
        for r in rows:
            results.append(r)
        if db and run:
            run.current_activity = (
                f"Agents analyzing indicator {indicator_ids[idx]} ({idx + 1}/{len(indicator_ids)})..."
            )
            run.completed_indicators = len(set(r["indicator_id"] for r in results))
            await db.commit()

    # ── Step 4: Cross-indicator consistency check ──────────────────────────
    consistency_issues = _check_cross_indicator_consistency(results)
    if consistency_issues:
        logger.warning(f"[Analysis] Cross-indicator consistency issues found: {len(consistency_issues)}")
        for issue in consistency_issues:
            logger.warning(f"  {issue}")
        emit_event(run_id, "CONSISTENCY_WARNINGS",
                   f"{len(consistency_issues)} cross-indicator consistency issues",
                   agent="arbiter", data={"issues": consistency_issues})

    # ── Step 5: Clean up ChromaDB collection ─────────────────────────────────
    try:
        cleanup_collection(run_id)
    except Exception:
        logger.warning(f"[Analysis] Cleanup skipped for {run_id}", exc_info=True)

    logger.info(f"[Analysis] Complete. {len(results)} indicator results produced.")
    return results


async def _analyse_indicator(
    indicator_id: str,
    country: str,
    run_id: str,
    all_chunks: list[dict],
    indicator_chunks: list[dict],
    pillar_chunks: dict[str, list[dict]],
    has_embeddings: bool,
    has_provided_pdf: bool = False,
    knowledge_graph: LegalKnowledgeGraph | None = None,
) -> list[dict[str, Any]]:
    """Run the 3-agent pipeline for a single indicator using ONLY its own chunks.
    Falls back to sibling-indicator chunks from the same pillar when no
    indicator-specific documents were discovered.
    """

    meta = INDICATOR_QUESTION_BANK.get(indicator_id)
    if not meta:
        raise ValueError(f"Unknown indicator_id: {indicator_id}")

    valid_scores = VALID_SCORES.get(indicator_id, [1.0, 0.5, 0.0])

    # Hybrid retrieval limited to this indicator's chunks
    vector_chunks: list[dict] = []
    keyword_chunks: list[dict] = []

    # If no indicator-specific chunks, fall back to pillar-level chunks
    use_pillar_search = False
    if not indicator_chunks:
        pillar = indicator_id.split(".")[0]
        fallback = pillar_chunks.get(pillar, [])
        if fallback:
            logger.info(f"[Analysis] {indicator_id}: no indicator-specific chunks, "
                        f"falling back to {len(fallback)} pillar-{pillar} chunks")
            indicator_chunks = fallback
            use_pillar_search = True

    if has_embeddings:
        if use_pillar_search:
            vector_chunks = retrieve_top_k(
                query=meta.research_question, run_id=run_id, k=100
            )
        else:
            vector_chunks = retrieve_top_k(
                query=meta.research_question, run_id=run_id, k=100, indicator_id=indicator_id
            )

    keyword_chunks = _keyword_search(indicator_chunks, meta.keyword_seeds, k=50)

    # Merge with dedup — vector results FIRST
    seen = set()
    chunks = []
    for c in vector_chunks + keyword_chunks:
        fp = c.get("text", "")[:200]
        if fp not in seen:
            seen.add(fp)
            chunks.append(c)

    # ── Rerank merged chunks: keep top 20 most relevant ──
    from app.modules.analysis.embeddings import rerank_chunks
    if len(chunks) > 20:
        chunks = rerank_chunks(chunks, query=meta.research_question, top_k=20)
        logger.info(f"[Analysis] {indicator_id}: reranked {len(chunks)} chunks (kept top 20)")

    logger.info(f"[Analysis] {indicator_id}: {len(vector_chunks)} vector + {len(keyword_chunks)} keyword "
                f"→ {len(chunks)} merged chunks for LLM")

    # ── Country-relevance filter ──
    filtered = _filter_country_relevant_chunks(chunks, country)
    if len(filtered) < len(chunks):
        removed = len(chunks) - len(filtered)
        logger.info(f"[Analysis] {indicator_id}: filtered {removed} chunks mentioning only foreign countries")
        chunks = filtered

    # Collect known valid URLs from this indicator's source documents
    known_urls = set()
    for c in indicator_chunks:
        url = c.get("metadata", {}).get("source_url")
        if url:
            known_urls.add(url)
    known_texts = {c.get("text", "") for c in indicator_chunks}

    state: AnalysisState = {
        "country": country,
        "indicator_id": indicator_id,
        "indicator_title": meta.title,
        "research_question": meta.research_question,
        "valid_scores": valid_scores,
        "chunks": chunks,
        "prosecution_quote": None,
        "prosecution_citation": None,
        "prosecution_score": None,
        "prosecution_criteria_key": None,
        "prosecution_confidence": None,
        "prosecution_reasoning": None,
        "defense_counter_quote": None,
        "defense_exception_found": False,
        "defense_adjusted_score": None,
        "defense_criteria_key": None,
        "defense_confidence": None,
        "defense_reasoning": None,
        "final_score": None,
        "final_criteria_key": None,
        "act_and_practice": None,
        "coverage": None,
        "impact_comments": None,
        "timeframe": None,
        "references": None,
        "note": None,
        "final_confidence": None,
        "final_quote": None,
        "final_citation": None,
        "not_found": False,
        "semantic_warning": "",
    }

    emit_event(run_id, "PROSECUTION_START", f"Prosecution analyzing {indicator_id} with {len(chunks)} indicator-specific chunks",
               agent="prosecution", indicator_id=indicator_id, data={"chunk_count": len(chunks)})
    state = await run_prosecution(state)
    emit_event(run_id, "PROSECUTION_DONE",
               f"Prosecution score={state.get('prosecution_score')} confidence={state.get('prosecution_confidence')}",
               agent="prosecution", indicator_id=indicator_id,
               data={"score": state.get("prosecution_score"), "confidence": state.get("prosecution_confidence"),
                     "quote": state.get("prosecution_quote"), "citation": state.get("prosecution_citation")})

    emit_event(run_id, "DEFENSE_START", f"Defense reviewing {indicator_id}",
               agent="defense", indicator_id=indicator_id)
    state = await run_defense(state)
    emit_event(run_id, "DEFENSE_DONE",
               f"Defense exception_found={state.get('defense_exception_found')} adjusted_score={state.get('defense_adjusted_score')}",
               agent="defense", indicator_id=indicator_id,
               data={"exception_found": state.get("defense_exception_found"),
                     "adjusted_score": state.get("defense_adjusted_score"),
                     "confidence": state.get("defense_confidence")})

    emit_event(run_id, "ARBITER_START", f"Arbiter reconciling {indicator_id}",
               agent="arbiter", indicator_id=indicator_id)
    state = await run_arbiter(state)
    emit_event(run_id, "ARBITER_DONE",
               f"Arbiter final_score={state.get('final_score')} not_found={state.get('not_found')}",
               agent="arbiter", indicator_id=indicator_id,
               data={"final_score": state.get("final_score"), "not_found": state.get("not_found"),
                     "confidence": state.get("final_confidence")})

    # ── Post-analysis validation: strip hallucinated content ──────────────
    state = _validate_against_source(state, known_urls, known_texts)

    # ── Knowledge graph supersession check ───────────────────────────────
    if knowledge_graph is not None and knowledge_graph.graph.number_of_nodes() > 0:
        supersession_note = _check_supersession(state, knowledge_graph)
        if supersession_note:
            state["note"] = (state.get("note") or "") + supersession_note

    # ── Enforced rules layer: override LLM output programmatically ──────
    enforcement = enforce_indicator_rules(
        indicator_id=indicator_id,
        act_and_practice=state.get("act_and_practice"),
        final_quote=state.get("final_quote"),
        final_score=state.get("final_score", 0.0),
    )
    if enforcement["override"]:
        logger.warning(f"[Enforce] {indicator_id}: rule enforcement triggered — "
                       f"score {state.get('final_score')} → {enforcement['new_score']}")
        state["final_score"] = enforcement["new_score"]
        state["not_found"] = enforcement["new_not_found"]
        state["note"] = (state.get("note") or "") + f" | {enforcement['note']}"
        state["final_confidence"] = 0.1
        state["final_criteria_key"] = None

    pillar_id = int(indicator_id.split(".")[0])
    from app.modules.discovery.sample_kit_checker import resolve_discovery_tag

    base_result = {
        "indicator_id": indicator_id,
        "pillar_id": pillar_id,
        "final_score": state.get("final_score", 0.0),
        "act_and_practice": state.get("act_and_practice"),
        "coverage": state.get("coverage"),
        "impact_comments": state.get("impact_comments"),
        "timeframe": state.get("timeframe"),
        "references": state.get("references"),
        "note": state.get("note"),
        "confidence": state.get("final_confidence"),
        "verbatim_quote": state.get("final_quote"),
        "article_citation": state.get("final_citation"),
        "law_number_ref": state.get("law_number_ref"),
        "location_ref": state.get("location_ref") or country,
        "prosecution_score": state.get("prosecution_score"),
        "defense_score": state.get("defense_adjusted_score"),
        "arbiter_score": state.get("final_score"),
        "not_found": state.get("not_found", False),
        "discovery_tag": resolve_discovery_tag(country, state.get("act_and_practice") or ""),
        "source_pdf_path": None,
        "mapping_rationale": (state.get("impact_comments") or "")[:300],
    }

    # Expand multi-law results into separate rows
    # Each law entry now carries its OWN metadata extracted from chunks:
    # law_number_ref, article_citation, verbatim_quote, timeframe are all
    # per-law, NOT copied from the primary law's result.
    multi_laws = state.get("multi_laws")
    if multi_laws and isinstance(multi_laws, list) and len(multi_laws) > 0:
        results = [base_result]
        for law_entry in multi_laws:
            law_name = law_entry.get("act_and_practice")
            row = dict(base_result)
            row["act_and_practice"] = law_name
            row["coverage"] = law_entry.get("coverage", base_result["coverage"])
            row["impact_comments"] = law_entry.get("impact_comments", base_result["impact_comments"])
            row["timeframe"] = law_entry.get("timeframe") or base_result.get("timeframe")
            row["references"] = law_entry.get("references", base_result["references"])
            row["note"] = law_entry.get("note", base_result["note"])
            row["law_number_ref"] = law_entry.get("law_number_ref")
            row["article_citation"] = law_entry.get("article_citation")
            row["verbatim_quote"] = law_entry.get("verbatim_quote")
            row["discovery_tag"] = resolve_discovery_tag(country, law_name or "")
            results.append(row)
        return results

    return [base_result]


def _uniform_sample(items: list, target: int) -> list:
    """Sample `target` items uniformly from `items`, preserving order.
    Uses proportional spacing so the first, middle, and tail are all represented."""
    if not items or target >= len(items):
        return items
    step = len(items) / target
    return [items[int(i * step)] for i in range(target)]


def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy comparison: lowercase, collapse whitespace, strip punctuation."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _semantic_similarity(quote: str, chunk_text: str) -> float:
    """
    Compute a simple word-overlap similarity as a fast semantic fallback.
    Returns 0.0–1.0 score. Used when exact substring match fails.
    """
    q_words = set(_normalize_text(quote).split())
    c_words = set(_normalize_text(chunk_text).split())
    if not q_words or not c_words:
        return 0.0
    intersection = q_words & c_words
    # Jaccard-like: intersection / min(len(q), len(c)) — favors recall of quote words
    return len(intersection) / max(len(q_words), 1)


def _validate_against_source(
    state: AnalysisState,
    known_urls: set[str],
    known_texts: set[str],
) -> AnalysisState:
    """
    Validate LLM-generated references and quotes against actual source documents.
    Two-layer validation:
      1. Exact substring match (strict)
      2. Normalized fuzzy match + semantic similarity (lenient fallback)
    If both fail, the result is invalidated as hallucinated.
    """
    references = state.get("references")
    quote = state.get("final_quote")
    citation = state.get("final_citation")
    not_found = state.get("not_found", False)

    if not_found:
        if references:
            logger.warning(f"[Validate] NOT_FOUND but references present — clearing hallucinated refs")
            state["references"] = None
        if quote:
            logger.warning(f"[Validate] NOT_FOUND but quote present — clearing hallucinated quote")
            state["final_quote"] = None
        if citation:
            state["final_citation"] = None
        return state

    if references:
        valid_refs = []
        for line in references.split("\n"):
            line_stripped = line.strip()
            if any(known_url in line_stripped for known_url in known_urls):
                valid_refs.append(line_stripped)
            elif line_stripped.startswith("http") and not any(u in line_stripped for u in known_urls):
                logger.warning(f"[Validate] Stripping hallucinated URL from references: {line_stripped[:80]}")
                continue
            else:
                valid_refs.append(line_stripped)
        if not valid_refs:
            state["references"] = None
        else:
            state["references"] = "\n".join(valid_refs)

    if quote and known_texts:
        # Layer 1: Exact substring match (strict)
        quote_normalised = quote.strip().lower()
        found_exact = any(quote_normalised in chunk_text.lower() for chunk_text in known_texts)

        # Layer 2: Normalized fuzzy match (lenient)
        found_fuzzy = False
        best_similarity = 0.0
        if not found_exact:
            quote_normalized_fuzzy = _normalize_text(quote)
            for chunk_text in known_texts:
                chunk_normalized = _normalize_text(chunk_text)
                if quote_normalized_fuzzy in chunk_normalized:
                    found_fuzzy = True
                    break
                sim = _semantic_similarity(quote, chunk_text)
                best_similarity = max(best_similarity, sim)
                if sim >= 0.75:
                    found_fuzzy = True
                    break

        if found_exact or found_fuzzy:
            logger.info(f"[Validate] Quote verified: exact={found_exact} fuzzy={found_fuzzy} sim={best_similarity:.2f}")
        else:
            logger.warning(
                f"[Validate] Verbatim quote not found in any source chunk — marking not_found "
                f"(exact={found_exact} fuzzy={found_fuzzy} best_sim={best_similarity:.2f})"
            )
            state["final_quote"] = None
            state["final_score"] = 0.0
            state["not_found"] = True
            state["act_and_practice"] = None
            state["coverage"] = "N/A"
            state["impact_comments"] = "LLM hallucinated quote not present in source documents."
            state["timeframe"] = None
            state["references"] = None
            state["note"] = "Quote was not found in any discovered document — result invalidated."
            state["final_confidence"] = 0.1

    # Always enrich references with ALL chunk source URLs
    chunk_urls = set()
    for c in state.get("chunks", []):
        url = c.get("metadata", {}).get("source_url")
        if url:
            chunk_urls.add(url)
    existing_refs = set()
    if state.get("references"):
        for line in state["references"].split("\n"):
            line = line.strip()
            if line:
                existing_refs.add(line)
    combined = existing_refs | chunk_urls
    if combined:
        state["references"] = "\n".join(sorted(combined))
        logger.info(f"[Validate] References: {len(existing_refs)} from LLM + {len(chunk_urls)} from chunks = {len(combined)} total")

    return state


def _keyword_search(chunks: list[dict], keyword_seeds: list[str], k: int = 15) -> list[dict]:
    """
    Enhanced keyword-based retrieval.
    Scores each chunk by keyword hit count AND section-number regex matches.
    Boosts chunks containing section references (e.g. "Section 26", "s. 26", "s 26").
    """
    if not chunks:
        return []

    stop_words = {"the", "a", "an", "in", "on", "of", "to", "for", "and", "or", "is", "are",
                  "does", "this", "country", "have", "what", "how", "any", "all", "that",
                  "with", "by", "from", "as", "at", "be", "it", "its", "not", "no", "but"}

    terms = set()
    for seed in keyword_seeds:
        terms.add(seed.lower())
        for word in seed.lower().split():
            if len(word) >= 4 and word not in stop_words:
                terms.add(word)

    # Precompile section-number regex patterns
    section_patterns = [
        re.compile(r"(?i)\bsection\s+\d+[\.\d]*"),
        re.compile(r"(?i)\bs\.\s*\d+[\.\d]*"),
        re.compile(r"(?i)\bs\s+\d+[\.\d]*"),
        re.compile(r"(?i)\barticle\s+\d+[\.\d]*"),
        re.compile(r"(?i)\bchapter\s+\d+[\.\d]*"),
        re.compile(r"(?i)\bpara(?:graph)?\s*\d+[\.\d]*"),
        re.compile(r"(?i)\bsubsection?\s*\d+[\.\d]*"),
    ]

    scored = []
    for chunk in chunks:
        text_lower = chunk.get("text", "").lower()
        keyword_hits = sum(1 for t in terms if t in text_lower)
        # Boost for section-number patterns
        section_boost = 0
        for pat in section_patterns:
            section_boost += len(pat.findall(chunk.get("text", "")))
        total_score = keyword_hits + (section_boost * 3)  # section matches weighted 3x
        if keyword_hits > 0 or section_boost > 0:
            scored.append((total_score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]


# Mapping of common country names to their demonyms (lowercased).
# Used by the country-relevance filter to detect foreign-law contamination.
_COUNTRY_DEMONYMS: dict[str, str] = {
    "australia": "australian",
    "bangladesh": "bangladeshi",
    "brazil": "brazilian",
    "canada": "canadian",
    "china": "chinese",
    "france": "french",
    "germany": "german",
    "ghana": "ghanaian",
    "india": "indian",
    "indonesia": "indonesian",
    "japan": "japanese",
    "kenya": "kenyan",
    "korea": "korean",
    "malaysia": "malaysian",
    "mexico": "mexican",
    "myanmar": "myanmar",
    "nepal": "nepalese",
    "netherlands": "dutch",
    "nigeria": "nigerian",
    "pakistan": "pakistani",
    "philippines": "filipino",
    "russia": "russian",
    "singapore": "singaporean",
    "south africa": "south african",
    "sri lanka": "sri lankan",
    "switzerland": "swiss",
    "thailand": "thai",
    "uk": "british",
    "united kingdom": "british",
    "united states": "american",
    "usa": "american",
    "vietnam": "vietnamese",
}

# Non-country legal frameworks that indicate a non-target legal discussion.
_FOREIGN_MARKERS = [
    "GDPR", "General Data Protection Regulation",
    "CCPA", "California Consumer Privacy Act",
    "PIPEDA", "LGPD", "POPIA",
    "DPDP Act", "Personal Data Protection Bill",
]


def _filter_country_relevant_chunks(chunks: list[dict], country: str) -> list[dict]:
    """
    Remove chunks whose text only discusses countries OTHER than the target
    country.  Keeps chunks that mention:
      - the target country (by name or demonym)
      - no country names at all (neutral legal text)
      - only generic cross-border terms (EU, GDPR, international — alone without
        a specific foreign country mention)
    """
    if not chunks or not country:
        return chunks

    target_lower = country.strip().lower()
    target_demonym = _COUNTRY_DEMONYMS.get(target_lower)

    # ── Target patterns ──────────────────────────────────────────────────
    target_tokens = {target_lower}
    if target_demonym:
        target_tokens.add(target_demonym)
    # Also add individual words for compound names e.g. "south" + "africa"
    for part in target_lower.split():
        if len(part) > 2:
            target_tokens.add(part)
    target_re = re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in target_tokens) + r")\b",
        re.IGNORECASE,
    )

    # ── Foreign patterns (everything except the target) ───────────────────
    foreign_tokens: set[str] = set()
    for cn, demo in _COUNTRY_DEMONYMS.items():
        if cn == target_lower or demo == target_demonym:
            continue
        # Add full compound country name and its demonym only —
        # NOT individual sub-words like 'south', 'new', 'sri' which are common English words.
        # This prevents directional words from polluting the foreign filter.
        foreign_tokens.add(cn)
        foreign_tokens.add(demo)
    foreign_re = re.compile(
        r"\b(?:" + "|".join(re.escape(f) for f in foreign_tokens) + r")\b",
        re.IGNORECASE,
    )

    foreign_markers_re = re.compile(
        r"\b(?:" + "|".join(re.escape(m) for m in _FOREIGN_MARKERS) + r")\b",
        re.IGNORECASE,
    )

    kept: list[dict] = []
    for chunk in chunks:
        text = chunk.get("text", "")
        if not text:
            kept.append(chunk)
            continue

        has_target = bool(target_re.search(text))
        has_foreign = bool(foreign_re.search(text))
        has_marker = bool(foreign_markers_re.search(text))

        if has_target:
            kept.append(chunk)
        elif not has_foreign and not has_marker:
            kept.append(chunk)
        else:
            logger.debug(
                f"[CountryFilter] Dropping chunk with foreign mention "
                f"but no target '{country}': {text[:120]}..."
            )
            continue

    return kept


def _make_error_result(indicator_id: str, error_msg: str) -> dict[str, Any]:
    """Create a placeholder error result when analysis fails for an indicator."""
    pillar_id = int(indicator_id.split(".")[0])
    return {
        "indicator_id": indicator_id,
        "pillar_id": pillar_id,
        "final_score": None,
        "act_and_practice": None,
        "coverage": None,
        "impact_comments": f"Analysis failed: {error_msg}",
        "timeframe": None,
        "references": None,
        "note": f"ERROR: {error_msg}",
        "confidence": 0.0,
        "verbatim_quote": None,
        "article_citation": None,
        "prosecution_score": None,
        "defense_score": None,
        "arbiter_score": None,
        "not_found": True,
        "discovery_tag": "NEW",
        "source_pdf_path": None,
        "location_ref": None,
        "processing_time": None,
        "mapping_rationale": None,
    }


def _check_supersession(state: AnalysisState, kg: LegalKnowledgeGraph) -> str | None:
    """
    Use the legal knowledge graph to check if the cited law/article has been
    superseded or amended. Returns a note string if supersession is found.
    """
    act_and_practice = state.get("act_and_practice") or ""
    if not act_and_practice:
        return None
    article_match = re.search(r"(?:Article|Section|s\.?)\s*(\d+[\.\d]*)", act_and_practice, re.IGNORECASE)
    if not article_match:
        return None
    article_num = article_match.group(1)
    supersession_notes = []
    for node in kg.graph.nodes:
        if article_num in node:
            resolved = kg.resolve_supersession(node)
            if resolved != node:
                supersession_notes.append(f"Article {article_num} may be superseded by {resolved}")
    if supersession_notes:
        note = " [Supersession: " + "; ".join(supersession_notes) + "]"
        return note
    return None


def _check_cross_indicator_consistency(results: list[dict]) -> list[str]:
    """
    Check for logical contradictions across indicator results.
    E.g. Pillar 6 siblings giving contradictory scores for the same law.
    """
    issues = []
    pillar_results: dict[int, list[dict]] = {}
    for r in results:
        pid = r.get("pillar_id")
        if pid:
            pillar_results.setdefault(pid, []).append(r)

    for pid, indicators in pillar_results.items():
        scored = [r for r in indicators if r.get("final_score") is not None and r.get("final_score", 0) > 0]
        zero_scores = [r for r in indicators if r.get("final_score") is not None and r.get("final_score", 0) == 0]
        if scored and zero_scores:
            laws_with_scores = {r.get("act_and_practice") for r in scored if r.get("act_and_practice")}
            laws_without = {r.get("act_and_practice") for r in zero_scores if r.get("act_and_practice")}
            common_laws = laws_with_scores & laws_without
            if common_laws:
                for law in common_laws:
                    scored_ids = [r["indicator_id"] for r in scored if r.get("act_and_practice") == law]
                    zero_ids = [r["indicator_id"] for r in zero_scores if r.get("act_and_practice") == law]
                    issues.append(
                        f"Pillar {pid}: '{law}' scored positively in {scored_ids} "
                        f"but scored 0.0 in {zero_ids} — possible contradiction"
                    )
            same_pillar_high = [r for r in scored if r.get("final_score", 0) >= 0.5]
            if len(same_pillar_high) >= 2:
                laws = [(r["indicator_id"], r.get("act_and_practice")) for r in same_pillar_high]
                issues.append(
                    f"Pillar {pid}: multiple indicators scored ≥0.5: {laws} — "
                    f"verify these are distinct restrictions, not double-counting"
                )
    return issues

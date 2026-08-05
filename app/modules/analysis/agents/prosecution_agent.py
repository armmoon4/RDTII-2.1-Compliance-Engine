"""
Module 2 — Prosecution Agent
Searches for the STRONGEST evidence that a restriction exists for a given indicator.
Returns verbatim quote, article citation, identified criteria key (mapped to score by code),
and confidence.
"""
import logging
import re
import unicodedata
from typing import Any

from app.modules.analysis.agents.ai_client import call_llm_json_async
from app.modules.analysis.agents.state import AnalysisState
from app.modules.analysis.indicator_mapper import map_semantic_context
from app.modules.analysis.scoring_engine import (
    criteria_to_score,
    format_criteria_for_prompt,
    get_criteria_keys,
    validate_score,
)

logger = logging.getLogger(__name__)

# Lightweight law-name pattern for reasoning verification only (catching act references)
_LAW_NAME_IN_REASONING = re.compile(
    r'\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|of|the|and|for|in|on)){0,5}'
    r'\s+(?:Act|Regulation|Code|Treaty|Convention|Directive|Ordinance|Decree|Order)\b'
    r'(?:\s*\(?[12]\d{3}\)?)?'
)

PROSECUTION_SYSTEM = """You are an expert legal analyst for the UNESCAP RDTII 2.1 Digital Trade Regulatory Index, operating in the PROSECUTION role. Your function is to identify the strongest available evidence that a trade-restrictive measure exists in the target country's legal framework. You operate under strict evidence-grounding constraints: every claim must be directly traceable to verbatim text in the provided document excerpts. You have no external knowledge — the excerpts are the entirety of your admissible evidence base. Output only valid JSON; no markdown, no preamble, no commentary."""

PROSECUTION_PROMPT_TEMPLATE = """
================================================================================
RDTII 2.1 PROSECUTION BRIEF
================================================================================

TARGET: {country}
INDICATOR: {indicator_id} — {indicator_title}
RESEARCH QUESTION: {research_question}

================================================================================
SCORING CRITERIA
================================================================================

{criteria_table}

================================================================================
ADMISSIBLE EVIDENCE — DOCUMENT EXCERPTS
================================================================================
These excerpts are the ONLY source material available. They represent the complete set of discovered documents for this indicator. No external knowledge, training data, or prior familiarity with {country}'s laws may be used. If text does not appear verbatim below, it does not exist for purposes of this analysis.

{chunks_text}
================================================================================

INSTRUCTIONS — PROSECUTION ANALYSIS

Step 1 — Scan ALL excerpts for language that indicates a trade-restrictive measure relevant to the research question. Look for: mandatory requirements, prohibitions, licensing, prior approval, data localization, source code disclosure, quantitative restrictions, discriminatory treatment, or other barriers.

Step 2 — Identify ALL distinct laws/provisions that contain restrictive language. Do not stop at one — list every relevant legal instrument found. Select the STRONGEST piece of evidence for the primary "quote" field, and note all other laws/provisions found in the "reasoning" field.

Step 3 — Extract the verbatim quote character-for-character, preserving punctuation, capitalization, spacing, and line structure. Every character in the output quote must match the source exactly.

Step 4 — Identify any section/article/chapter number present in the same vicinity as the quote. If none exists in the excerpts, this field is null.

Step 5 — Map the evidence to exactly one criteria key from the SCORING CRITERIA table. The key captures the TYPE of restriction; the numeric score is derived automatically from the key.

Step 6 — Assign confidence:
  · ≥0.7: Direct statutory language from a primary legal source (act, regulation, code) that unambiguously matches a criteria key.
  · 0.4–0.6: Secondary source (government policy, official guideline) that clearly indicates a restriction but is not legislative text.
  · ≤0.3: Commentary, blog post, news article, academic analysis, or ambiguous/indirect language. Also ≤0.3 if the criteria fit is uncertain.

OUTPUT SCHEMA — RESPOND WITH EXACTLY THIS JSON STRUCTURE:
{{
  "quote": "<string or null — verbatim restriction/prohibition language, character-for-character from excerpts>",
  "citation": "<string or null — section/article number ONLY (e.g. 'Section 26(1)'), never an act/regulation name>",
  "criteria_key": "<string or null — exact key from SCORING CRITERIA table>",
  "confidence": "<float 0.0–1.0 — per confidence rules above>",
  "reasoning": "<string — concise rationale including ALL laws/provisions found, grounded in excerpt text>"
}}

VALIDATION RULES — YOUR OUTPUT MUST SATISFY ALL OF THE FOLLOWING:

1. QUOTE GROUNDING: The quote must be VERBATIM restriction or prohibition language (e.g. "must not", "shall not", "is prohibited", "requires prior approval", "must be located"). Descriptive phrases like "legislative framework for", "governs the sharing of", "establishes rules for" are NOT restriction text — they merely describe the law's existence. The quote MUST appear as an exact substring in at least one document excerpt. If uncertain, set quote=null.

2. CITATION GROUNDING: Citation MUST be ONLY a section/article number (e.g. "Section 26(1)", "Article 9.2", "s 123") that appears verbatim in the excerpts. NEVER include an act or regulation name in the citation field. NEVER prepend "of the X Act". The citation field is for a structural reference number ONLY. If no section/article number appears verbatim anywhere in the excerpts, set citation=null.

3. CRITERIA KEY VALIDITY: The criteria_key must be an exact match of a key listed in the SCORING CRITERIA table. No aliases, no variations, no invented keys.

4. REASONING GROUNDING: The reasoning must reference specific language from the excerpts and list ALL laws/provisions found. Generic statements such as "this is a restriction" without excerpt support are insufficient.

5. CONFIDENCE CALIBRATION: If the source is a secondary document (blog, commentary, summary, news article, academic analysis) rather than a primary legal text (act, regulation, code), confidence must be ≤0.3 regardless of how clear the language appears.

6. NULL HANDLING: If no relevant provision exists in any excerpt, ALL of quote, citation, and criteria_key must be null.

EDGE CASES:
· The excerpts describe a law but do not quote its text → set quote=null, citation=null, criteria_key=null, confidence=0.3. Do NOT fabricate the law's text from knowledge.
· The excerpts contain only a URL/title and no substantive text → same as above.
· Multiple relevant provisions exist in DIFFERENT laws → select the single strongest one for the quote, but list ALL laws found in the reasoning field. The Arbiter will handle multiple laws.
· The restriction is implied but not explicit → confidence ≤0.3. Quote only the text that implies it, not an invented explicit version.

NEGATIVE EXAMPLE — DO NOT DO THIS:
{{
  "quote": "The legislative framework for the Australian Government's My Health Record system",  // WRONG: descriptive phrase, not a restriction/prohibition text
  "citation": "Privacy Act 1988",  // WRONG: act name in citation field — NEVER put act names here; also no section number
  "criteria_key": "data_localization",  // WRONG: key not in criteria table
  "confidence": 0.8,  // WRONG: source is a blog post, should be ≤0.3
  "reasoning": "This describes the legislative framework."  // WRONG: not grounded in restriction language
}}

POSITIVE EXAMPLE — DO THIS INSTEAD:
{{
  "quote": "An APP entity must not use or disclose personal information about an individual for the purpose of direct marketing.",
  "citation": "Section 26(1)",
  "criteria_key": "restriction_on_data_use",
  "confidence": 0.85,
  "reasoning": "Section 26(1) of the Privacy Act 1988 (appearing verbatim in Document 4) imposes a mandatory prohibition on using personal information for direct marketing, which directly matches 'restriction_on_data_use' criteria. Also identified: the My Health Records Act 2012 (Section 12) in Document 7, which imposes additional restrictions on health data transfers."
}}

If NO relevant evidence exists in any excerpt, respond with:
{{
  "quote": null,
  "citation": null,
  "criteria_key": null,
  "confidence": 0.3,
  "reasoning": "No relevant provision found in the provided document excerpts for {country} / {indicator_id}. Indicates either no restriction exists or documents for this indicator do not contain applicable legal text."
}}
"""


def _normalize_text(text: str) -> str:
    """Normalize unicode, case, and whitespace for reliable substring matching."""
    text = unicodedata.normalize('NFKC', text)
    text = text.lower()
    text = re.sub(r'[\u2018\u2019]', "'", text)
    text = re.sub(r'[\u201c\u201d]', '"', text)
    text = re.sub(r'[\u2013\u2014]', '-', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _word_overlap_similarity(text_a: str, text_b: str) -> float:
    """Compute what fraction of shorter text's words appear in the longer text."""
    words_a = set(_normalize_text(text_a).split())
    words_b = set(_normalize_text(text_b).split())
    if not words_a or not words_b:
        return 0.0
    shorter = words_a if len(words_a) <= len(words_b) else words_b
    longer = words_b if len(words_a) <= len(words_b) else words_a
    if not shorter:
        return 0.0
    intersection = shorter & longer
    return len(intersection) / len(shorter)


def _quote_is_explicit(quote: str) -> bool:
    """Check if a quote contains explicit restriction language vs implied/hedged."""
    q = quote.lower()
    has_strong = bool(re.search(r'\b(must|shall|require[sd]?|prohibit[sd]?|mandatory|obligation|compel)\b', q))
    has_weak = bool(re.search(r'\b(may|might|could|should|would|encourage|consider|suggest|aim[s]?|seek[s]?)\b', q))
    if has_strong and not has_weak:
        return True
    if has_strong and has_weak:
        return None  # ambiguous
    return False


def _verify_reasoning(
    reasoning: str,
    *,
    chunks_text_norm: str,
    chunks_used: int,
    verified_quote: str | None = None,
    verified_citation: str | None = None,
    criteria_key: str | None = None,
    exception_found: bool | None = None,
    counter_quote: str | None = None,
) -> str:
    """Cross-field reasoning consistency verifier.
    
    Checks every factual claim in the reasoning against verified fields and evidence.
    Returns the original reasoning with a verification note appended if issues found.
    """
    if not reasoning or len(reasoning.strip()) < 20:
        return "Insufficient reasoning provided. [Note: reasoning too short or empty.]"

    r_lower = reasoning.lower()
    issues: list[str] = []

    # 1. Document reference validity
    doc_refs = re.findall(r'(?:\[DOCUMENT\s+(\d+)\]|Document\s+(\d+))\b', reasoning)
    for a, b in doc_refs:
        ref_num = int(a or b)
        if ref_num > chunks_used:
            issues.append(f"References Document {ref_num} but only {chunks_used} available")

    # 2. Quote term inclusion — the reasoning should reference key terms from the quote
    if verified_quote:
        quote_words = {w for w in re.findall(r"[A-Za-z]{4,}", verified_quote.lower()) if w not in _STOP_WORDS}
        if quote_words:
            reasoning_words = set(re.findall(r"[A-Za-z]{4,}", r_lower))
            overlap = quote_words & reasoning_words
            min_expected = max(2, int(len(quote_words) * 0.25))
            if len(overlap) < min_expected:
                issues.append("Does not reference key terms from the verified quote")

    # 3. Criteria key mention
    if criteria_key:
        key_terms = criteria_key.lower().replace("_", " ")
        if key_terms not in r_lower and criteria_key.lower() not in r_lower:
            issues.append(f"Does not reference the selected criteria key '{criteria_key}'")

    # 4. Citation mention
    if verified_citation:
        cit_terms = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", verified_citation)}
        if cit_terms and not any(t in r_lower for t in cit_terms):
            issues.append("Does not reference the verified citation")

    # 5. Exception consistency (defense context)
    if exception_found is True:
        exc_keywords = {"exception", "exempt", "carve", "saving", "does not apply", "notwithstanding", "subject to"}
        if not any(k in r_lower for k in exc_keywords):
            issues.append("exception_found=true but no exception language in reasoning")
        if counter_quote:
            cq_terms = {w for w in re.findall(r"[A-Za-z]{4,}", counter_quote.lower()) if w not in _STOP_WORDS}
            if cq_terms and not (cq_terms & set(re.findall(r"[A-Za-z]{4,}", r_lower))):
                issues.append("Does not reference the verified counter-quote")
    elif exception_found is False:
        # Check for exception language, but exclude negated patterns
        # like "no exception" or "not exempt" which are valid for false.
        exc_pos = re.findall(r'\b(exception|exempt|carve.out|saving clause)\b', r_lower)
        exc_neg = re.findall(r'\b(no\s+exception|not\s+exempt|no\s+carve)\b', r_lower)
        if len(exc_pos) > len(exc_neg):
            issues.append("exception_found=false but mentions exception language")

    # 6. Law name grounding — catch law-like patterns in reasoning
    for m in _LAW_NAME_IN_REASONING.finditer(reasoning):
        law_name = m.group(0).strip()
        law_name_norm = _normalize_text(law_name)
        if law_name_norm.lower() not in chunks_text_norm.lower():
            issues.append(f"References '{law_name}' not found verbatim in any excerpt")

    # 7. Null-field consistency — no quote + no key should imply not-found language
    if not verified_quote and not criteria_key and not exception_found:
        found_indicators = {"no restriction", "no relevant", "no evidence", "nothing found", "not found", "could not identify", "does not exist"}
        if not any(p in r_lower for p in found_indicators):
            issues.append("No quote or criteria_key but reasoning does not indicate 'not found'")

    # 8. Self-contradiction
    pos_indicators = {"restricts", "prohibits", "requires", "mandates", "limits", "bars", "blocks"}
    neg_indicators = {"no restriction", "not restrictive", "permissive", "allows", "permits"}
    has_pos = any(p in r_lower for p in pos_indicators)
    has_neg = any(p in r_lower for p in neg_indicators)
    if criteria_key and has_neg and not has_pos:
        issues.append("Reasoning contradicts criteria_key (says 'no restriction' but key implies restriction exists)")
    if not criteria_key and has_pos:
        issues.append("Reasoning describes a restriction but no criteria_key selected")

    if not issues:
        return reasoning

    # Append verification note to reasoning
    reasoning = reasoning.strip().rstrip(".")
    note = "; ".join(issues[:3])
    if len(issues) > 3:
        note += f" (+{len(issues)-3} more)"
    return f"{reasoning}. [Reasoning note: {note}.]"


# Stop words for reasoning verification term overlap
_STOP_WORDS = frozenset({
    "this", "that", "with", "from", "have", "been", "were", "they", "them",
    "their", "will", "would", "could", "should", "shall", "must", "may",
    "also", "than", "then", "some", "any", "each", "every", "both",
    "more", "most", "other", "such", "into", "about", "over", "after",
    "before", "between", "under", "above", "these", "those", "because",
    "there", "where", "which", "while", "what", "when", "been", "being",
    "does", "done", "made", "said", "used", "using", "just", "very",
    "well", "much", "still", "even", "though", "although",
})


async def run_prosecution(state: AnalysisState) -> AnalysisState:
    """
    LangGraph node — Prosecution Agent.
    Mutates and returns the AnalysisState with prosecution fields populated.
    The LLM identifies a criteria_key; the code maps it to a numeric score.
    """
    indicator_id = state["indicator_id"]
    country = state["country"]
    chunks = state.get("chunks", [])

    if not chunks:
        logger.warning(f"[Prosecution] No chunks for {indicator_id} — marking NOT_FOUND.")
        return {
            **state,
            "prosecution_quote": None,
            "prosecution_citation": None,
            "prosecution_score": 0.0,
            "prosecution_confidence": 0.1,
            "prosecution_reasoning": "No document excerpts were available for analysis.",
        }

    # Track truncation
    chunks_total = len(chunks)
    chunks_used = min(chunks_total, 60)
    chunks_truncated = chunks_used < chunks_total

    # Build chunk text with source attribution
    chunks_text = _format_chunks(chunks)
    chunks_text_for_llm = chunks_text[:25000]
    if len(chunks_text) > 25000:
        chunks_truncated = True

    # Apply semantic context warning — use same window the LLM sees
    ctx = map_semantic_context(chunks_text_for_llm, indicator_id)
    semantic_warning = ctx.get("semantic_warning") or ""
    if semantic_warning:
        logger.info(f"[Prosecution] Semantic warning for {indicator_id}: {semantic_warning}")

    criteria_table = format_criteria_for_prompt(indicator_id)

    # Escape curly braces in all dynamic values to prevent str.format() KeyError
    def _esc(s):
        return str(s).replace("{", "{{").replace("}", "}}")
    prompt = PROSECUTION_PROMPT_TEMPLATE.format(
        country=_esc(country),
        indicator_id=_esc(indicator_id),
        indicator_title=_esc(state["indicator_title"]),
        research_question=_esc(state["research_question"]),
        criteria_table=_esc(criteria_table),
        chunks_text=_esc(chunks_text_for_llm),
    )

    if semantic_warning:
        prompt += f"\n\nIMPORTANT WARNING: {semantic_warning}"

    logger.info(f"[Prosecution] Calling LLM for {country} / {indicator_id}")
    result: dict[str, Any] = await call_llm_json_async(prompt, PROSECUTION_SYSTEM)

    if not result:
        return {
            **state,
            "prosecution_quote": None,
            "prosecution_citation": None,
            "prosecution_score": 0.0,
            "prosecution_confidence": 0.1,
            "prosecution_reasoning": "LLM returned no parseable response.",
        }

    # ---- VERIFICATION LAYER ------------------------------------------------
    raw_quote = result.get("quote")
    raw_citation = result.get("citation")
    raw_criteria_key = result.get("criteria_key")
    raw_confidence = result.get("confidence", 0.5)
    raw_reasoning = result.get("reasoning", "")

    # Normalize chunks text once for all substring checks
    chunks_norm = _normalize_text(chunks_text)

    # 1. Quote grounding verification
    verified_quote = None
    if raw_quote and isinstance(raw_quote, str) and raw_quote.strip():
        quote_norm = _normalize_text(raw_quote)
        if quote_norm in chunks_norm:
            verified_quote = raw_quote.strip()
        else:
            # Fallback 1: try aggressive normalization (strip everything)
            quote_aggressive = re.sub(r'[^a-z0-9\s]', ' ', quote_norm)
            quote_aggressive = re.sub(r'\s+', ' ', quote_aggressive).strip()
            chunks_aggressive = re.sub(r'[^a-z0-9\s]', ' ', chunks_norm)
            chunks_aggressive = re.sub(r'\s+', ' ', chunks_aggressive).strip()
            if len(quote_aggressive) > 20 and quote_aggressive in chunks_aggressive:
                logger.info(f"[Prosecution] Quote found via aggressive normalization")
                verified_quote = raw_quote.strip()
                raw_confidence = min(raw_confidence, 0.4)
            else:
                # Fallback 2: word overlap similarity
                sim = _word_overlap_similarity(raw_quote, chunks_text)
                if sim >= 0.75:
                    logger.info(f"[Prosecution] Quote verified via word overlap (sim={sim:.2f})")
                    verified_quote = raw_quote.strip()
                    raw_confidence = min(raw_confidence, 0.35)
                else:
                    logger.warning(f"[Prosecution] Quote not found verbatim in excerpts (sim={sim:.2f}): {raw_quote!r}")
    else:
        verified_quote = None

    # 2. Citation grounding verification
    verified_citation = None
    if raw_citation and isinstance(raw_citation, str) and raw_citation.strip():
        cit_norm = _normalize_text(raw_citation)
        if cit_norm in chunks_norm:
            verified_citation = raw_citation.strip()
        else:
            logger.warning(f"[Prosecution] Citation not found verbatim in excerpts: {raw_citation!r}")
    else:
        verified_citation = None

    # 3. Lightweight NLI check: is the quote explicit or implied?
    if verified_quote:
        explicit = _quote_is_explicit(verified_quote)
        if explicit is False:
            logger.info(f"[Prosecution] Quote is implied (not explicit): {verified_quote!r}")
            raw_confidence = min(raw_confidence, 0.3)
        elif explicit is None:
            logger.info(f"[Prosecution] Quote has mixed explicit/implied language: {verified_quote!r}")
            raw_confidence = min(raw_confidence, 0.5)

    # 4. Confidence clamping
    try:
        confidence = max(0.0, min(1.0, float(raw_confidence)))
    except (ValueError, TypeError):
        confidence = 0.3

    # 5. Criteria key validation against source of truth
    valid_keys = get_criteria_keys(indicator_id)
    criteria_key = None
    if raw_criteria_key and isinstance(raw_criteria_key, str):
        if raw_criteria_key in valid_keys:
            criteria_key = raw_criteria_key
        else:
            logger.warning(
                f"[Prosecution] Unknown criteria_key '{raw_criteria_key}' for {indicator_id} "
                f"— valid keys: {valid_keys}"
            )

    # ---- SCORE MAPPING (deterministic, from validated key) -----------------
    if criteria_key:
        mapped_score = criteria_to_score(indicator_id, criteria_key)
        if mapped_score is not None:
            validated_score = validate_score(indicator_id, mapped_score)
        else:
            validated_score = 0.0
    else:
        validated_score = 0.0

    # If quote was hallucinated but criteria key happens to be valid, still allow
    # the score to pass through — but drop confidence further as warning signal.
    if raw_quote and not verified_quote:
        confidence = min(confidence, 0.1)
        criteria_key = None
        validated_score = 0.0

    # 6. Reasoning consistency verification
    verified_reasoning = _verify_reasoning(
        raw_reasoning,
        chunks_text_norm=chunks_norm,
        chunks_used=chunks_used,
        verified_quote=verified_quote,
        verified_citation=verified_citation,
        criteria_key=criteria_key,
    )

    return {
        **state,
        "prosecution_quote": verified_quote,
        "prosecution_citation": verified_citation,
        "prosecution_score": validated_score,
        "prosecution_criteria_key": criteria_key,
        "prosecution_confidence": confidence,
        "prosecution_reasoning": verified_reasoning,
        "semantic_warning": semantic_warning,
        "prosecution_chunks_truncated": chunks_truncated,
        "prosecution_chunks_total": chunks_total,
        "prosecution_chunks_used": chunks_used,
    }


def _format_chunks(chunks: list[dict]) -> str:
    """Format chunk list into readable text blocks for the prompt."""
    max_chunks = 60
    if len(chunks) > max_chunks:
        logger.info(
            f"[Prosecution] Truncating {len(chunks)} chunks to {max_chunks} "
            f"for LLM context window"
        )
    parts = []
    for i, chunk in enumerate(chunks[:max_chunks]):
        meta = chunk.get("metadata", {})
        source = meta.get("source_url", "Unknown source")
        text = chunk.get("text", "")
        parts.append(f"[DOCUMENT {i+1} — Source: {source}]\n{text}\n")
    return "\n---\n".join(parts)

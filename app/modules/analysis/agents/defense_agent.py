"""
Module 2 — Defense Agent
Searches for counter-evidence: exceptions, exemptions, savings clauses, carve-outs.
If the prosecution score was 0.0, the defense agent confirms NOT_FOUND.
The LLM identifies a criteria_key; the code maps it to the adjusted numeric score.
"""
import logging
from typing import Any

from app.modules.analysis.agents.ai_client import call_llm_json_async
from app.modules.analysis.agents.prosecution_agent import _normalize_text, _verify_reasoning
from app.modules.analysis.agents.state import AnalysisState
from app.modules.analysis.scoring_engine import (
    criteria_to_score,
    format_criteria_for_prompt,
    get_criteria_keys,
    validate_score,
)

logger = logging.getLogger(__name__)

DEFENSE_SYSTEM = """You are an expert legal analyst for the UNESCAP RDTII 2.1 Digital Trade Regulatory Index, operating in the DEFENSE role. Your function is to scrutinize the prosecution's evidence and identify any countervailing factors — exceptions, exemptions, carve-outs, savings clauses, or scope limitations — that would reduce or eliminate the alleged restriction. You operate under strict evidence-grounding constraints: every claim must be directly traceable to verbatim text in the provided document excerpts. You have no external knowledge — the excerpts are the entirety of your admissible evidence base. Output only valid JSON; no markdown, no preamble, no commentary."""

DEFENSE_PROMPT_TEMPLATE = """
================================================================================
RDTII 2.1 DEFENSE BRIEF
================================================================================

TARGET: {country}
INDICATOR: {indicator_id} — {indicator_title}

================================================================================
PROSECUTION CASE UNDER REVIEW
================================================================================

  Criteria Key: {prosecution_criteria_key}
  Implied Score: {prosecution_score}
  Evidence Quote: "{prosecution_quote}"
  Citation: {prosecution_citation}
  Reasoning: {prosecution_reasoning}

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

INSTRUCTIONS — DEFENSE ANALYSIS

Step 1 — Verify the prosecution's claim. Read the prosecution's quote and confirm whether it appears verbatim in the provided excerpts. If the quote is not present verbatim, this is a hallucination — note this in reasoning.

Step 2 — Scan the excerpts for ANY countervailing language: exceptions, exemptions, carve-outs, savings clauses, scope limitations, applicability conditions, sunset dates, or provisions that limit the restriction to specific sectors, entities, or circumstances.

Step 3 — Check criteria classification. Does the prosecution's selected criteria key correctly describe the restriction? Consider: if the rule only applies to government data (not commercial data), the restriction may not apply to this indicator. If the rule has an exception that eliminates the restriction, select a criteria key that reflects NO restriction (score 0.0).

Step 4 — If an exception is found, extract the counter-quote character-for-character, preserving punctuation, capitalization, spacing, and line structure.

Step 5 — Select the corrected criteria key that reflects the restriction AFTER accounting for any exceptions found. The criteria key is mapped to a numeric score by the system — do NOT pick a number.

Step 6 — Assign confidence:
  · ≥0.7: Exception is explicit statutory language from a primary legal source, unambiguously reducing the restriction.
  · 0.4–0.6: Exception is from a secondary source or policy document with clear language.
  · ≤0.3: Exception is ambiguous, implied, from a blog/commentary, or the criteria reclassification is uncertain.

OUTPUT SCHEMA — RESPOND WITH EXACTLY THIS JSON STRUCTURE:

When an exception IS found:
{{
  "exception_found": true,
  "counter_quote": "<string — character-for-character verbatim exception text from excerpts, or null>",
  "exception_description": "<string — plain-English explanation grounded in excerpts>",
  "criteria_key": "<string — corrected criteria key from table, reflecting post-exception state>",
  "confidence": "<float 0.0–1.0 — per confidence rules above>",
  "reasoning": "<string — rationale for exception finding and criteria change, grounded in excerpt text>"
}}

When NO exception is found and prosecution criteria is correct:
{{
  "exception_found": false,
  "counter_quote": null,
  "exception_description": null,
  "criteria_key": "{prosecution_criteria_key}",
  "confidence": "<float 0.0–1.0 — per confidence rules above>",
  "reasoning": "<string — confirmation that no exception exists in excerpts, prosecution criteria stands>"
}}

VALIDATION RULES — YOUR OUTPUT MUST SATISFY ALL OF THE FOLLOWING:

1. EXCEPTION GROUNDING: "exception_found" may be true ONLY if exception-related language appears verbatim in the excerpts. Inferences about implied exceptions without supporting text are insufficient.

2. COUNTER-QUOTE GROUNDING: The counter_quote must appear as an exact substring in at least one document excerpt. Character-for-character match required including punctuation and spacing. If no verbatim exception text exists, counter_quote must be null.

3. EXCEPTION DESCRIPTION GROUNDING: The description must reference specific language from the excerpts. Generic statements such as "there may be an exception" without excerpt support are invalid.

4. CRITERIA KEY VALIDITY: The criteria_key must be an exact match of a key listed in the SCORING CRITERIA table. If the exception fully eliminates the restriction, select the key corresponding to score 0.0 (typically "no_restriction" or equivalent).

5. CONFIDENCE CALIBRATION: If the source is a secondary document (blog, commentary, summary) rather than a primary legal text, confidence must be ≤0.3 regardless of how clear the exception language appears.

6. PROSECUTION QUOTE VERIFICATION: If the prosecution's quote is not found verbatim in the excerpts, note this in the reasoning field. The evidence base is only the excerpts — the prosecution may have hallucinated.

EDGE CASES:
· The prosecution found nothing (quote=null, criteria_key=null) → confirm exception_found=false, counter_quote=null, criteria_key=null. Defense is moot.
· The exception is partial (reduces but does not eliminate the restriction) → select the criteria key that reflects the reduced restriction level.
· The excerpts contain no exception language at all → exception_found=false, confirm prosecution criteria.
· The prosecution mis-cited a section number → note the correct section number from excerpts in reasoning, adjust criteria if needed.

NEGATIVE EXAMPLE — DO NOT DO THIS:
{{
  "exception_found": true,
  "counter_quote": "There may be exceptions to this rule",  // WRONG: not verbatim from excerpts
  "exception_description": "The law probably has a general exception",  // WRONG: speculation, not grounded
  "criteria_key": "no_restriction",  // WRONG: no evidence of complete exception
  "confidence": 0.8,  // WRONG: speculative exception
  "reasoning": "Based on my knowledge of this country's laws..."  // WRONG: used external knowledge
}}

POSITIVE EXAMPLE — DO THIS INSTEAD:
{{
  "exception_found": true,
  "counter_quote": "This section does not apply to the use of personal information for the primary purpose for which it was collected.",
  "exception_description": "Section 27(2) explicitly exempts primary-purpose use from the direct marketing restriction, eliminating the restriction for this specific use case.",
  "criteria_key": "no_restriction",
  "confidence": 0.9,
  "reasoning": "Section 27(2) of the Privacy Act (verbatim in Document 4) creates a direct exception to the Section 26(1) restriction identified by prosecution. The restriction does not apply to primary-purpose use, which covers the majority of standard data processing activities."
}}

If the prosecution found NO evidence (prosecution_quote is null or "None"), respond with:
{{
  "exception_found": false,
  "counter_quote": null,
  "exception_description": null,
  "criteria_key": null,
  "confidence": 0.9,
  "reasoning": "Prosecution found no restriction evidence for {country} / {indicator_id}. Defense review is moot — no exception analysis required."
}}
"""


async def run_defense(state: AnalysisState) -> AnalysisState:
    """
    LangGraph node — Defense Agent.
    Mutates and returns the AnalysisState with defense fields populated.
    """
    indicator_id = state["indicator_id"]
    country = state["country"]
    chunks = state.get("chunks", [])
    prosecution_score = state.get("prosecution_score", 0.0)
    prosecution_criteria_key = state.get("prosecution_criteria_key")

    # If no prosecution evidence, defense confirms NOT_FOUND (regardless of chunks)
    if prosecution_score == 0.0 and not state.get("prosecution_quote"):
        return {
            **state,
            "defense_counter_quote": None,
            "defense_exception_found": False,
            "defense_adjusted_score": 0.0,
            "defense_criteria_key": prosecution_criteria_key,
            "defense_confidence": 0.9,
            "defense_reasoning": "Prosecution found no restriction. Defense concurs.",
        }

    # No chunks available — cannot find counter-evidence
    if not chunks:
        return {
            **state,
            "defense_counter_quote": None,
            "defense_exception_found": False,
            "defense_adjusted_score": prosecution_score,
            "defense_criteria_key": prosecution_criteria_key,
            "defense_confidence": 0.3,
            "defense_reasoning": "No document excerpts available to search for counter-evidence.",
        }

    # Prioritize chunks for defense to ensure exceptions aren't truncated out of the 60-chunk window.
    # 1. Chunk with prosecution quote (so defense sees what they are defending against)
    # 2. Chunks with exception keywords
    exception_keywords = {'except', 'exempt', 'carve', 'not apply', 'notwithstanding', 'subject to', 'unless', 'provided that'}
    prosecution_quote = state.get("prosecution_quote")
    pq_norm = _normalize_text(prosecution_quote) if prosecution_quote else None

    def _score_chunk_for_defense(c: dict) -> int:
        text = c.get("text", "").lower()
        score = 0
        if pq_norm and pq_norm in _normalize_text(text):
            score += 1000  # Must include the quote we are defending against
        score += sum(1 for kw in exception_keywords if kw in text)
        return score

    chunks = sorted(chunks, key=_score_chunk_for_defense, reverse=True)

    # Track truncation
    chunks_total = len(chunks)
    chunks_used = min(chunks_total, 60)
    chunks_truncated = chunks_used < chunks_total

    chunks_text = _format_chunks(chunks)
    chunks_text_for_llm = chunks_text[:25000]
    if len(chunks_text) > 25000:
        chunks_truncated = True

    criteria_table = format_criteria_for_prompt(indicator_id)

    def _esc(s):
        return str(s).replace("{", "{{").replace("}", "}}")
    prompt = DEFENSE_PROMPT_TEMPLATE.format(
        country=_esc(country),
        indicator_id=_esc(indicator_id),
        indicator_title=_esc(state["indicator_title"]),
        prosecution_criteria_key=_esc(prosecution_criteria_key or "null"),
        prosecution_score=_esc(prosecution_score),
        prosecution_quote=_esc(state.get("prosecution_quote") or "None"),
        prosecution_citation=_esc(state.get("prosecution_citation") or "None"),
        prosecution_reasoning=_esc(state.get("prosecution_reasoning") or "None"),
        criteria_table=_esc(criteria_table),
        chunks_text=_esc(chunks_text_for_llm),
    )

    semantic_warning = state.get("semantic_warning", "")
    if semantic_warning:
        prompt += f"\n\nIMPORTANT WARNING: {semantic_warning}"

    logger.info(f"[Defense] Calling LLM for {country} / {indicator_id}")
    result: dict[str, Any] = await call_llm_json_async(prompt, DEFENSE_SYSTEM)

    if not result:
        # LLM failed — default: no exception found
        return {
            **state,
            "defense_counter_quote": None,
            "defense_exception_found": False,
            "defense_adjusted_score": prosecution_score,
            "defense_criteria_key": prosecution_criteria_key,
            "defense_confidence": 0.3,
            "defense_reasoning": "LLM returned no response for defense analysis.",
        }

    # ---- VERIFICATION LAYER ------------------------------------------------
    raw_counter_quote = result.get("counter_quote")
    raw_exception_found = result.get("exception_found", False)
    raw_criteria_key = result.get("criteria_key")
    raw_confidence = result.get("confidence", 0.5)
    raw_reasoning = result.get("reasoning", "")

    chunks_norm = _normalize_text(chunks_text)

    # 1. Counter-quote grounding verification
    verified_counter_quote = None
    if raw_counter_quote and isinstance(raw_counter_quote, str) and raw_counter_quote.strip():
        cq_norm = _normalize_text(raw_counter_quote)
        if cq_norm in chunks_norm:
            verified_counter_quote = raw_counter_quote.strip()
        else:
            logger.warning(f"[Defense] Counter-quote not found verbatim in excerpts: {raw_counter_quote!r}")

    # If exception claimed but no verifiable counter-quote, invalidate
    exception_found = bool(raw_exception_found)
    if exception_found and not verified_counter_quote:
        logger.warning("[Defense] exception_found=true but counter_quote not verifiable — forcing to false")
        exception_found = False

    # 2. Verify prosecution quote exists in chunks (hallucination check)
    prosecution_quote = state.get("prosecution_quote")
    prosecution_hallucinated = False
    if prosecution_quote and isinstance(prosecution_quote, str) and prosecution_quote.strip():
        pq_norm = _normalize_text(prosecution_quote)
        if pq_norm not in chunks_norm:
            prosecution_hallucinated = True
            logger.warning(f"[Defense] Prosecution quote not verifiable in chunks: {prosecution_quote!r}")

    # 3. Criteria key validation against source of truth
    valid_keys = get_criteria_keys(indicator_id)
    criteria_key = raw_criteria_key or prosecution_criteria_key
    if criteria_key and criteria_key not in valid_keys:
        logger.warning(
            f"[Defense] Unknown criteria_key '{criteria_key}' for {indicator_id} "
            f"— valid keys: {valid_keys}, falling back to prosecution key"
        )
        criteria_key = prosecution_criteria_key

    # 4. Confidence clamping
    try:
        confidence = max(0.0, min(1.0, float(raw_confidence)))
    except (ValueError, TypeError):
        confidence = 0.3

    # 5. Downgrade confidence if prosecution hallucinated (defense couldn't verify)
    if prosecution_hallucinated:
        confidence = min(confidence, 0.3)
        if not exception_found:
            # If prosecution's quote is imaginary, defense can't do useful work
            criteria_key = None

    # ---- SCORE MAPPING ----------------------------------------------------
    if criteria_key:
        mapped_score = criteria_to_score(indicator_id, criteria_key)
        if mapped_score is not None:
            adjusted_score = validate_score(indicator_id, mapped_score)
        else:
            adjusted_score = prosecution_score
    else:
        adjusted_score = prosecution_score

    # ---- REASONING VERIFICATION --------------------------------------------
    verified_reasoning_defense = _verify_reasoning(
        raw_reasoning,
        chunks_text_norm=chunks_norm,
        chunks_used=chunks_used,
        verified_quote=verified_counter_quote,
        verified_citation=None,
        criteria_key=criteria_key,
        exception_found=exception_found,
        counter_quote=verified_counter_quote,
    )

    return {
        **state,
        "defense_counter_quote": verified_counter_quote,
        "defense_exception_found": exception_found,
        "defense_adjusted_score": adjusted_score,
        "defense_criteria_key": criteria_key,
        "defense_confidence": confidence,
        "defense_reasoning": verified_reasoning_defense,
        "defense_chunks_truncated": chunks_truncated,
        "defense_chunks_total": chunks_total,
        "defense_chunks_used": chunks_used,
    }


def _format_chunks(chunks: list[dict]) -> str:
    """Format chunk list into readable text blocks for the prompt."""
    max_chunks = 60
    if len(chunks) > max_chunks:
        logger.info(
            f"[Defense] Truncating {len(chunks)} chunks to {max_chunks} "
            f"for LLM context window"
        )
    parts = []
    for i, chunk in enumerate(chunks[:max_chunks]):
        meta = chunk.get("metadata", {})
        source = meta.get("source_url", "Unknown source")
        text = chunk.get("text", "")
        parts.append(f"[DOCUMENT {i+1} — Source: {source}]\n{text}\n")
    return "\n---\n".join(parts)

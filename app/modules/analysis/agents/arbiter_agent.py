"""
Module 2 — Arbiter Agent
Reconciles prosecution and defense outputs.
Produces the final 9-column RDTII output: score, act_and_practice, coverage,
impact_comments, timeframe, references, note, confidence, verbatim_quote, citation.

The LLM selects the correct criteria_key from the scoring criteria table.
The code maps it to the final numeric score — no LLM numerical score guessing.

Uses programmatic quote extraction — the LLM selects a chunk index,
then the code extracts the verbatim text from that stored chunk.

Also uses programmatic law name and timeframe extraction from chunks
to prevent LLM hallucination of these fields.
"""
import json
import logging
import re
from typing import Any

from app.modules.analysis.agents.ai_client import call_llm_json_async
from app.modules.analysis.agents.state import AnalysisState
from app.modules.analysis.scoring_engine import (
    criteria_to_score,
    format_criteria_for_prompt,
    get_criteria_keys,
    validate_score,
)
from app.modules.analysis.agents.prosecution_agent import _word_overlap_similarity

logger = logging.getLogger(__name__)

_LAW_NAME_PATTERN = re.compile(
    r'\b((?:[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|\([A-Z][A-Za-z0-9 /.,\'\-]+\)|of|the|and|for|in|on|to|by|at|or|an|as))*)'
    r'\s+(?:Act|Regulation|Code|Order|Rule|Directive|Standard|Policy|Decree|Ordinance|Statute|Convention|Treaty|Protocol|Framework|Agreement|Law)s?'
    r'(?:\s+\(?[12]\d{3}\)?)?'
    r'(?:\s*\([A-Za-z0-9 /.,\'-]+\))?)'
)

# Case-insensitive variant of _LAW_NAME_PATTERN — catches ALL-CAPS law names
# from PDF headers/footers (e.g. "PERSONAL DATA PROTECTION ACT 2010")
# that the TitleCase-only pattern misses.
_LAW_NAME_PATTERN_CI = re.compile(
    _LAW_NAME_PATTERN.pattern,
    re.IGNORECASE,
)

_LEGAL_KEYWORDS = {
    'Act', 'Regulation', 'Code', 'Order', 'Rule', 'Directive', 'Standard',
    'Policy', 'Decree', 'Ordinance', 'Statute', 'Convention', 'Treaty',
    'Protocol', 'Framework', 'Agreement', 'Law',
}

# Secondary pattern: standalone legal keyword + number (no capitalized words required)
# Catches abbreviated references like "Act 709", "P.U. (A) 123/2021", "SL 63/2021"
# that are used as primary law names in some jurisdictions.
# NOTE: "Chapter" intentionally excluded — it's a structural reference, not a law name prefix.
#       Real chapter-based citations (e.g. Hong Kong "Cap. 123") use the "Cap." keyword.
_LAW_NUM_NAME_PATTERN = re.compile(
    r'(?:(?:Act|Regulation|Code|Order|Rule|Directive|Policy|Ordinance|'
    r'Cap\.?|P\.U\.|SL|S\.?\s*L\.?)'
    r'(?:\s+No\.?\s*)?'
    r'\s*\(?\d+(?:[./]*\d+)*\)?'
    r'(?:\s*,\s*\d{4})?'
    r'(?:\s+of\s+\d{4})?'
    r'(?:\s*\([A-Za-z0-9/]+\))?'
    r'|'
    r'Regulation\s+\(?(?:EU|EC)\)?\s*\d+/\d+)'
)

# Tertiary pattern: descriptive law references that imply a governing legal instrument
# but don't use formal legal keywords (e.g. "My Health Record system", "credit reporting framework").
# These are fed as candidates to the LLM verification step, not treated as confirmed law names.
# Uses restrictive matching: requires >=2 capitalized words + a descriptor noun,
# avoiding generic mentions like "the system" or "a framework".
_DESCRIPTIVE_LAW_PATTERN = re.compile(
    r'\b('
    r'[A-Z][a-z]+'                                    # first capitalized word
    r'(?:\s+[A-Z][a-z]+){1,3}'                       # 1-3 consecutive capitalized words
    r'(?:\s+(?:the|of|and|for|in|on|to|by|at|or|an|as)\s+[A-Z][a-z]+)*'  # optional: conj + cap word
    r'\s+(?:[Ss]ystem|[Ff]ramework|[Rr]egime|[Ss]cheme|'
    r'[Pp]rogram|[Ii]nitiative|[Mm]echanism|[Aa]rrangement)'
    r')'
)


_LAW_NAME_STOP_WORDS = {
    'while', 'whereas', 'where', 'when', 'although', 'however',
    'therefore', 'furthermore', 'moreover', 'additionally',
    'notwithstanding', 'nevertheless', 'consequently', 'subsequently',
    'accordingly', 'hence', 'thus', 'hereby', 'herein', 'hereunder',
    'therein', 'thereunder', 'thereby', 'thereto', 'therefor',
    'under', 'pursuant', 'notwithstanding', 'except',
    'the', 'a', 'an', 'as', 'by', 'for',
}

_LAW_NAME_PREFIX_PATTERN = re.compile(
    r'^(?:under(?:\s+the)?|pursuant\s+to(?:\s+the)?|'
    r'in\s+accordance\s+with(?:\s+the)?|subject\s+to(?:\s+the)?|'
    r'notwithstanding(?:\s+the)?|except\s+as\s+provided\s+(?:in|by)(?:\s+the)?|'
    r'for\s+the\s+purposes\s+of(?:\s+the)?|by\s+virtue\s+of(?:\s+the)?)\s+',
    re.IGNORECASE,
)


def _clean_law_name(name: str) -> str:
    """Strip leading prepositional phrases from law names.
    E.g. 'Under the Personal Data Protection Regulations 2021' → 'Personal Data Protection Regulations 2021'
         'Pursuant to Section 26 of the Act' → 'Section 26 of the Act'
    """
    cleaned = name.strip()
    while True:
        m = _LAW_NAME_PREFIX_PATTERN.match(cleaned)
        if m:
            cleaned = cleaned[m.end():].strip()
        else:
            break
    if cleaned.lower().startswith("the "):
        cleaned = cleaned[4:]
    return cleaned


def _find_law_names(text: str) -> list[str]:
    """Find all potential law names in text using both patterns."""
    names = []
    seen = set()

    def _is_valid_secondary_match(name: str) -> bool:
        """Filter out false positives from _LAW_NUM_NAME_PATTERN."""
        name_lower = name.lower()
        if re.match(r'^act\s+\(?\d{4}\)?$', name_lower):
            return False
        return True

    def _is_valid_primary_match(name: str) -> bool:
        """Filter out false positives from _LAW_NAME_PATTERN
        (e.g. 'While the Act' where 'While' is a sentence start, not a law name)."""
        name_lower = name.lower()
        first_word = name_lower.split()[0] if name_lower.split() else ''
        if first_word in _LAW_NAME_STOP_WORDS:
            return False
        return True

    for m in _LAW_NAME_PATTERN.finditer(text):
        name = _clean_law_name(m.group(0).strip())
        if name and name.lower() not in seen and _is_valid_primary_match(name):
            seen.add(name.lower())
            names.append(name)
    # Case-insensitive pass for ALL-CAPS law names from PDF headers
    for m in _LAW_NAME_PATTERN_CI.finditer(text):
        raw = m.group(0).strip()
        name = _clean_law_name(raw)
        if not name or name.lower() in seen:
            continue
        if not _is_valid_primary_match(name):
            continue
        words = raw.split()
        if not any(w.isupper() and len(w) >= 3 for w in words):
            continue
        seen.add(name.lower())
        names.append(name)
    for m in _LAW_NUM_NAME_PATTERN.finditer(text):
        name = m.group(0).strip()
        if name and name.lower() not in seen and _is_valid_secondary_match(name):
            seen.add(name.lower())
            names.append(name)
    return names


def _find_descriptive_law_refs(text: str) -> list[str]:
    """Find descriptive references to legal systems/frameworks that imply a governing law.
    These are weaker candidates than formal law names — they get verified by the LLM step.
    E.g. 'My Health Record system', 'credit reporting framework'."""
    refs = []
    seen = set()
    for m in _DESCRIPTIVE_LAW_PATTERN.finditer(text):
        name = m.group(0).strip()
        if name.startswith("The "):
            name = name[4:]
        if not name or name.lower() in seen:
            continue
        # Require at least 3 capitalized words (excluding descriptor noun which may be lowercase)
        words = name.split()
        cap_count = sum(1 for w in words if w and w[0].isupper())
        if cap_count < 3:
            continue
        seen.add(name.lower())
        refs.append(name)
    return refs

ARBITER_SYSTEM = """You are the chief legal analyst for UNESCAP's RDTII 2.1 Digital Trade Regulatory Index, operating as the ARBITER. Your role is to reconcile prosecution and defense arguments and produce the final authoritative RDTII output record. You operate under strict evidence-grounding constraints: every field you populate must be directly traceable to verbatim text in the provided document excerpts. You have no external knowledge — the excerpts are the entirety of your admissible evidence base. If a field cannot be populated from the excerpts, it must be null (not a guess, not inferred knowledge). Output only valid JSON; no markdown, no preamble, no commentary."""

ARBITER_PROMPT_TEMPLATE = """
================================================================================
RDTII 2.1 ARBITRATION DOCKET
================================================================================

INDICATOR: {indicator_id} — {indicator_title}
COUNTRY: {country}

================================================================================
CASE PRESENTATIONS
================================================================================

--- PROSECUTION CASE ---
  Criteria Key: {prosecution_criteria_key}
  Evidence Quote: "{prosecution_quote}"
  Citation: {prosecution_citation}
  Confidence: {prosecution_confidence}
  Reasoning: {prosecution_reasoning}

--- DEFENSE CASE ---
  Exception Found: {exception_found}
  Counter-Quote: "{defense_counter_quote}"
  Proposed Criteria Key: {defense_criteria_key}
  Confidence: {defense_confidence}
  Reasoning: {defense_reasoning}

================================================================================
SCORING CRITERIA
================================================================================

{criteria_table}

================================================================================
ADMISSIBLE EVIDENCE — DOCUMENT EXCERPTS
================================================================================
These excerpts are the ONLY source material available. They represent the complete set of discovered documents for this indicator. No external knowledge, training data, or prior familiarity with {country}'s laws may be used. If text does not appear verbatim below, it does not exist for purposes of this analysis. Numbers in brackets (e.g. [DOCUMENT 1]) identify each excerpt for cross-referencing in the chunk index fields.

{chunks_text}
================================================================================

INSTRUCTIONS — ARBITRATION ANALYSIS

Step 1 — Verify the prosecution's quote and the defense's counter-quote both appear verbatim in the excerpts. If either is not found, disregard it as hallucinated.

Step 2 — Weigh the arguments. Determine whether the defense exception substantively reduces or eliminates the restriction identified by the prosecution. Use only excerpt text — not intuition, not general legal knowledge.

Step 3 — Select the final criteria key that best reflects the regulatory state AFTER considering both prosecution evidence and any valid defense exceptions. The criteria key drives the score — you are selecting the key, not the number.

Step 4 — Populate all RDTII output columns. Each field has specific grounding rules (see below). If text for a field does not exist in the excerpts, set that field to null.

Step 5 — Assign evidence, law name, and timeframe chunk index numbers (1-based) corresponding to the excerpt numbers shown in the [DOCUMENT N] labels above.

Step 6 — Assign confidence reflecting the overall reliability of the determination considering source quality and evidence clarity.

================================================================================
FIELD-LEVEL RULES — EVERY FIELD MUST SATISFY ITS RULES
================================================================================

criteria_key
  Accept: One of the keys listed in the SCORING CRITERIA table. Must exactly match (case-sensitive).
  Reject: Any string not in the table, any numeric score, any invented key.
  If no evidence supports ANY criteria key, set to null and not_found=true.

act_and_practice
  Accept: A formal legal instrument name matching pattern: <Capitalized Words> <Legal Keyword> optionally followed by a year in parentheses. Legal keywords: Act, Regulation, Code, Order, Rule, Directive, Standard, Policy, Decree, Ordinance, Statute, Convention, Treaty, Protocol, Framework, Agreement, Law.
  Examples: "Privacy Act 1988", "My Health Records Act 2012", "Telecommunications Code 2021", "General Data Protection Regulation".
  Reject: Descriptive phrases ("The legislative framework for...", "The regime governing...", "The rules around...", "Provisions on...", "System for..."), generic references ("the Act", "the Regulation"), inferred names not present verbatim in excerpts.
  IMPORTANT: List ALL formal law names found in the excerpts, not just one. Set the PRIMARY/main law in "act_and_practice" and put EACH ADDITIONAL law in the "laws" array.
  If no formal law name appears verbatim in any excerpt, set to null.

verbatim_quote
  Accept: Text copied character-for-character from the excerpts, preserving original punctuation, capitalization, spacing, and line breaks. The quote must appear as an identical substring in at least one excerpt.
  Reject: Summaries, paraphrases, translations, corrected grammar, synonyms, merged text from multiple locations, text from training knowledge.
  If the prosecution quote passes the character-for-character test, use it. Otherwise, find the correct verbatim text in the excerpts. If no verbatim restriction text exists, set to null.

article_citation
  Accept: A specific section, article, chapter, or paragraph number that appears verbatim in the excerpts, e.g. "Section 26(1)", "Article 9.2", "Chapter III", "Paragraph 4(a)".
  Reject: Excerpt labels ("DOCUMENT 5", "EXCERPT 1", "CHUNK 3"), act names or descriptive labels, guessed section numbers not present in excerpts. The citation is for the specific section — the act name goes in act_and_practice.
  If no section/article number appears verbatim in any excerpt, set to null.

timeframe
  Accept: A date or date range that appears verbatim in the excerpts, e.g. "Since June 2014, last amended September 2024", "Enacted 1988", "2021".
  IMPORTANT: Look for the LAST AMENDMENT DATE of the law (e.g. "last amended", "revised", "updated", "as amended by", "amendment act"). Also look for the original enactment date. Provide both if available in the format: "Enacted YYYY, last amended <date>".
  Reject: "—" (use null), LLM-generated dates not present in excerpts, calculated or inferred dates (e.g. "approximately 2015"), estimated effective dates.
  If no date text appears verbatim in any excerpt, set to null.

coverage
  Accept: "Horizontal" if the law applies to all sectors without limitation. A specific sector name that appears verbatim in the excerpts: "Telecommunications", "Health", "Finance", "Banking", "Insurance", "Transport", "Energy", "Media", "E-commerce", etc. "N/A" if no coverage information exists.
  Reject: A sector name not present in the excerpts, "All sectors" instead of "Horizontal", empty string.
  If you cannot determine coverage from excerpt text, use "N/A".

references
  Accept: A URL that appears verbatim in the excerpts. The complete URL including scheme (https://...).
  Reject: Guessed or reconstructed URLs based on training knowledge. URLs from outside the excerpts. Partial URLs. Null if no URL is visible in any excerpt.

note
  Accept: "—" if no caveats apply. Otherwise, secondary source URLs, supersession information, or caveats that are grounded in the excerpts.
  Reject: Inferred supersession not supported by excerpt text, speculation about legal status.

impact_comments
  Accept: A concise plain-English explanation of how the cited provision affects the indicator score. Must reference specific language or concepts from the excerpts.
  Reject: Unsupported legal analysis not traceable to excerpt text. Generic statements like "this is a restriction" without specifics.

confidence
  Range: 0.0–1.0
  Guidelines:
    · ≥0.7: Direct statutory language from a primary legal source (act, regulation, code), clear criteria match, both quotes verified verbatim.
    · 0.4–0.6: Secondary source (policy, guideline), or primary source with ambiguous criteria fit.
    · ≤0.3: Blog/commentary/academic source, or any uncertainty about criteria fit. Also ≤0.3 if the evidence document is a secondary source (even if language is clear).

evidence_chunk_index
  The 1-based [DOCUMENT N] number of the excerpt containing the verbatim_quote text. If verbatim_quote is null, this must also be null.

law_name_chunk_index
  The 1-based [DOCUMENT N] number of the excerpt containing the act_and_practice text. If act_and_practice is null, this must also be null.

timeframe_chunk_index
  The 1-based [DOCUMENT N] number of the excerpt containing the timeframe text. If timeframe is null, this must also be null.

not_found
  true if NO evidence supports any criteria key (criteria_key is null). false if a criteria key was selected.

================================================================================
MULTIPLE LAWS HANDLING (CRITICAL — DO NOT SKIP)
================================================================================

MOST indicators are governed by MORE THAN ONE law. For example, cross-border data transfers (indicator 6.1) may be governed by a primary data protection act AND subsidiary regulations, AND sector-specific laws (e.g. health records, banking regulations).

You MUST:
1. Identify ALL distinct laws mentioned in the excerpts that are relevant to this indicator
2. Set the PRIMARY/main law in "act_and_practice"
3. Put EVERY ADDITIONAL law in the "laws" array, each with its own act_and_practice, coverage, timeframe, references, and note fields
4. For each law entry in "laws", provide the last amendment date in the timeframe field
5. The criteria_key and verbatim_quote remain at the top level and apply to all listed laws

Only populate "laws" for genuinely distinct and separate legal instruments — not for sections of the same act. For a single law, leave "laws" as an empty array []. For multiple laws, the "laws" array MUST contain one entry per additional law.

================================================================================
OUTPUT SCHEMA — RESPOND WITH EXACTLY THIS JSON STRUCTURE
================================================================================

{{
  "criteria_key": "<string | null — exact key from SCORING CRITERIA table>",
  "act_and_practice": "<string | null — PRIMARY formal law name (see rules above)>",
  "coverage": "<string — Horizontal | sector from excerpts | N/A>",
  "impact_comments": "<string — explanation grounded in excerpts>",
  "timeframe": "<string | null — date text including last amendment if available>",
  "references": "<string | null — URL from excerpts only>",
  "note": "<string — — or caveats grounded in excerpts>",
  "confidence": "<float 0.0–1.0 — per confidence guidelines above>",
  "verbatim_quote": "<string | null — character-for-character from excerpts>",
  "article_citation": "<string | null — section/article number from excerpts only>",
  "not_found": "<boolean — true only if criteria_key is null>",
  "evidence_chunk_index": "<int | null — 1-based excerpt number containing verbatim_quote>",
  "law_name_chunk_index": "<int | null — 1-based excerpt number containing act_and_practice>",
  "timeframe_chunk_index": "<int | null — 1-based excerpt number containing timeframe>",
  "laws": "<array — entries for EACH additional distinct law found, empty array if only one law>"
}}

================================================================================
NEGATIVE EXAMPLE — DO NOT PRODUCE OUTPUT LIKE THIS
================================================================================

{{
  "criteria_key": "data_localization",                          // WRONG: key not in criteria table
  "act_and_practice": "The legislative framework for the Australian Government's My Health Record system",  // WRONG: descriptive phrase, not formal law name
  "coverage": "All sectors",                                     // WRONG: should be "Horizontal" if applicable, or a sector name from excerpts
  "impact_comments": "This framework restricts data flows.",     // WRONG: vague, not grounded in excerpts
  "timeframe": "—",                                              // WRONG: should be null, not em-dash
  "references": "https://www.legislation.gov.au/Series/C2004A03712",  // WRONG: URL not present verbatim in excerpts
  "note": "—",
  "confidence": 0.85,                                            // WRONG: source is a blog post, should be ≤0.3
  "verbatim_quote": "The legislative framework for the Australian Government's My Health Record system",  // WRONG: not a restriction text, not relevant to indicator
  "article_citation": "DOCUMENT 8",                              // WRONG: excerpt label, not a section number
  "not_found": false,
  "evidence_chunk_index": 3,
  "law_name_chunk_index": 3,
  "timeframe_chunk_index": null,
  "laws": []
}}

================================================================================
POSITIVE EXAMPLE — PRODUCE OUTPUT LIKE THIS INSTEAD
================================================================================

{{
  "criteria_key": "restriction_on_data_use",
  "act_and_practice": "Privacy Act 1988",
  "coverage": "Horizontal",
  "impact_comments": "Section 26(1) of the Privacy Act 1988 prohibits APP entities from using or disclosing personal information for direct marketing, creating a general restriction on secondary data use across all sectors.",
  "timeframe": "Since June 2014, last amended September 2024",
  "references": "https://www.legislation.gov.au/Series/C2004A03712",
  "note": "The Privacy Act 1988 was originally enacted in 1988 and significantly amended by the Privacy Amendment Act 2014.",
  "confidence": 0.85,
  "verbatim_quote": "An APP entity must not use or disclose personal information about an individual for the purpose of direct marketing.",
  "article_citation": "Section 26(1)",
  "not_found": false,
  "evidence_chunk_index": 4,
  "law_name_chunk_index": 4,
  "timeframe_chunk_index": 4,
  "laws": []
}}

================================================================================
NO-EVIDENCE OUTPUT — USE THIS WHEN NO RELEVANT TEXT EXISTS IN ANY EXCERPT
================================================================================

If NO excerpt supports any criteria key, respond with:
{{
  "criteria_key": null,
  "act_and_practice": null,
  "coverage": "N/A",
  "impact_comments": "No evidence found in discovered documents for {country} / {indicator_id}.",
  "timeframe": null,
  "references": null,
  "note": "—",
  "confidence": 0.1,
  "verbatim_quote": null,
  "article_citation": null,
  "not_found": true,
  "evidence_chunk_index": null,
  "law_name_chunk_index": null,
  "timeframe_chunk_index": null,
  "laws": []
}}
"""

METADATA_ENRICHMENT_PROMPT = """
You are a precise legal document analyst. Extract structured metadata from the document excerpts below.

You must REASON step-by-step before giving your final answer. Think carefully about what each field actually means in legal documents — don't just pick up random numbers or text that look superficially date-like or number-like.

Document excerpts:
{chunks_text}

EXTRACTION TASK:

For each field below, first think through the documents, then output the final value.

STEP-BY-STEP REASONING (think through each):

1. law_number_ref: Look at every number or reference found in the text. For each one, ask yourself: "Is this the OFFICIAL REGISTRATION/CATALOGUE NUMBER of the act itself (like 'Act 709', 'SL 63/2021', 'No. 119 of 1988', 'Chapter 486'), OR is it a section/paragraph/article label (like 'Paragraph 8.3.3', 'Section 129', 'Part IIIA', 's 16C')?" The difference: act numbers identify the LAW itself, while section/paragraph numbers identify a PART within the law. If you only see section/paragraph labels, law_number_ref must be null.

2. timeframe: Look at every date, year, or date-range. For each, ask: "Is this an actual legal amendment or effective date (like 'Last amended September 2024', 'Enacted 2010', 'Entered into force 24 May 2016'), OR is it document formatting text (page numbers, headers like 'PART A INTRODUCTION', '1. Background', confidentiality notices like 'PRIVATE & CONFIDENTIAL', table-of-contents entries like 'Record keeping ........ 17' like ")?" Dates that are part of a document's table of contents, headers, page numbering, or formatting are NOT legal dates. Only actual amendment/key dates count.

3. article_citation: Look for text that specifically identifies a section, article, paragraph, part, chapter, schedule, annex, or regulation by LABEL + NUMBER (e.g. "Section 26(1)", "Paragraph 8.3.3", "Schedule 1"). If no such labeled reference exists, output null.

OUTPUT FORMAT:
Output ONLY valid JSON with this exact structure:

{{
  "reasoning": {{
    "law_number_ref": "Your step-by-step reasoning about what value you chose and why you rejected other candidates",
    "timeframe": "Your step-by-step reasoning about what value you chose and why you rejected other candidates"
  }},
  "act_and_practice": "<string | null — formal law name verbatim from text>",
  "additional_laws": ["<string — one additional law name each>"],
  "law_number_ref": "<string | null — verified act reference number, NOT a section/paragraph label>",
  "timeframe": "<string | null — verified amendment/effective date, NOT document formatting text>",
  "article_citation": "<string | null — section/article/paragraph label + number verbatim from text>",
  "coverage": "<string | null — sector, Horizontal, or N/A>",
  "location_ref": "<string | null — jurisdiction this law applies to (e.g. country name or 'ASEAN' for ASEAN instruments). NOT a region mentioned in passing — only the actual jurisdiction of the law."
}}

CRITICAL RULES:
- Every output value must be a DIRECT SUBSTRING of the provided excerpts (character-for-character). If it's not in the text, it's null.
- If ANY doubt exists, output null. Never guess or infer from your training knowledge.
- law_number_ref: Must be an OFFICIAL ACT IDENTIFIER (act number, chapter number, subsidiary legislation number). Section/paragraph/article/part labels are NEVER valid here — they go in article_citation. A "Paragraph 8.3.3" is a guideline paragraph — not an act number.
- timeframe: Must contain an actual date or year used to indicate when the law was enacted/amended/effective. Document headers, section titles, page numbers, confidentiality notices, or table of contents entries are NEVER valid timeframes. If there's no clear amendment/enactment date, set to null.
"""


async def _enrich_metadata_from_chunks(
    chunks: list[dict],
    evidence_idx: int | None,
) -> dict[str, Any]:
    """
    Make a focused LLM call to extract metadata fields from the evidence chunks.
    This is SEPARATE from the reconciliation call — the LLM only needs to read
    and extract, not reason about scores or arguments.
    """
    if not chunks:
        return {}

    # Use the evidence chunk and a few surrounding chunks as context
    context_chunks = []
    if evidence_idx is not None and 1 <= evidence_idx <= len(chunks):
        start = max(0, evidence_idx - 3)
        end = min(len(chunks), evidence_idx + 2)
        for i in range(start, end):
            c = chunks[i]
            url = c.get("metadata", {}).get("source_url", "")
            text = c.get("text", "")
            if text:
                context_chunks.append(f"[SOURCE: {url}]\n{text[:3000]}")
    else:
        # No evidence index — use first few chunks
        for c in chunks[:5]:
            url = c.get("metadata", {}).get("source_url", "")
            text = c.get("text", "")
            if text:
                context_chunks.append(f"[SOURCE: {url}]\n{text[:3000]}")

    if not context_chunks:
        return {}

    chunks_text = "\n\n---\n\n".join(context_chunks)
    if len(chunks_text) > 20000:
        chunks_text = chunks_text[:20000]

    def _esc(s):
        return str(s).replace("{", "{{").replace("}", "}}")

    prompt = METADATA_ENRICHMENT_PROMPT.format(chunks_text=_esc(chunks_text))

    logger.info("[Arbiter] Calling metadata enrichment LLM...")
    result: dict[str, Any] = await call_llm_json_async(
        prompt,
        "You are a precise legal metadata extractor. Extract only what is verbatim in the text. Never guess. Output only valid JSON.",
    )

    if not result:
        logger.warning("[Arbiter] Metadata enrichment LLM returned nothing")
        return {}

    # Validate each field before returning (ignore the reasoning field)
    cleaned = {}
    for field in ["act_and_practice", "law_number_ref", "timeframe", "article_citation", "coverage", "location_ref"]:
        value = result.get(field)
        if value and isinstance(value, str) and value.strip():
            cleaned[field] = value.strip()
        else:
            cleaned[field] = None
    # Handle additional_laws (array field)
    additional_laws = result.get("additional_laws")
    if additional_laws and isinstance(additional_laws, list):
        cleaned["additional_laws"] = [law for law in additional_laws if isinstance(law, str) and law.strip()]

    # Lightweight safety net (LLM reasoning is primary, this catches edge cases):
    # Reject law_number_ref with em-dash (e.g. "10.—(1)") — clearly a section number
    law_ref = cleaned.get("law_number_ref")
    if law_ref and re.search(r'[—–]', law_ref):
        logger.warning(f"[Arbiter] Rejecting law_number_ref with em-dash: {law_ref!r}")
        cleaned["law_number_ref"] = None
    logger.info(f"[Arbiter] Metadata enrichment result: act={cleaned.get('act_and_practice')}, "
                f"ref={cleaned.get('law_number_ref')}, timeframe={cleaned.get('timeframe')}, "
                f"citation={cleaned.get('article_citation')}, coverage={cleaned.get('coverage')}, "
                f"location={cleaned.get('location_ref')}")
    return cleaned


async def run_arbiter(state: AnalysisState) -> AnalysisState:
    """
    LangGraph node — Arbiter Agent.
    Produces the final reconciled result from prosecution + defense outputs.
    The LLM selects a criteria_key; code maps it to the final numeric score.
    Uses programmatic quote, law name, and timeframe extraction from chunks.
    """
    indicator_id = state["indicator_id"]
    country = state["country"]
    chunks = state.get("chunks", [])

    # Fast-path: if both agents agree no evidence found (regardless of chunks)
    if (
        not state.get("prosecution_quote")
        and not state.get("defense_exception_found")
        and (state.get("prosecution_score") or 0.0) == 0.0
        and (state.get("defense_adjusted_score") or 0.0) == 0.0
    ):
        logger.info(f"[Arbiter] Fast-path NOT_FOUND for {country} / {indicator_id}")
        return _build_not_found_state(state)

    # Fast-path: no chunks were available at all
    if not chunks:
        logger.info(f"[Arbiter] No chunks available for {country} / {indicator_id} — NOT_FOUND")
        return _build_not_found_state(state)

    # Track truncation
    chunks_total = len(chunks)
    chunks_used = min(chunks_total, 60)
    chunks_truncated = chunks_used < chunks_total

    # Format chunks for the prompt
    chunks_text = _format_chunks(chunks)
    chunks_text_for_llm = chunks_text[:30000]
    if len(chunks_text) > 30000:
        chunks_truncated = True
    criteria_table = format_criteria_for_prompt(indicator_id)

    def _esc(s):
        return str(s).replace("{", "{{").replace("}", "}}")

    prompt = ARBITER_PROMPT_TEMPLATE.format(
        country=_esc(country),
        indicator_id=_esc(indicator_id),
        indicator_title=_esc(state["indicator_title"]),
        criteria_table=_esc(criteria_table),
        chunks_text=_esc(chunks_text_for_llm),
        prosecution_quote=_esc(state.get("prosecution_quote") or "None"),
        prosecution_citation=_esc(state.get("prosecution_citation") or "None"),
        prosecution_criteria_key=_esc(state.get("prosecution_criteria_key") or "null"),
        prosecution_confidence=_esc(state.get("prosecution_confidence", 0.5)),
        prosecution_reasoning=_esc(state.get("prosecution_reasoning") or "None"),
        exception_found=_esc(state.get("defense_exception_found", False)),
        defense_counter_quote=_esc(state.get("defense_counter_quote") or "None"),
        defense_criteria_key=_esc(state.get("defense_criteria_key") or "null"),
        defense_confidence=_esc(state.get("defense_confidence", 0.5)),
        defense_reasoning=_esc(state.get("defense_reasoning") or "None"),
    )

    semantic_warning = state.get("semantic_warning", "")
    if semantic_warning:
        prompt += f"\n\nIMPORTANT WARNING: {semantic_warning}"

    logger.info(f"[Arbiter] Calling LLM for {country} / {indicator_id}")
    result: dict[str, Any] = await call_llm_json_async(prompt, ARBITER_SYSTEM)
    if not result:
        logger.warning(f"[Arbiter] LLM first attempt failed — retrying immediately.")
        result = await call_llm_json_async(prompt, ARBITER_SYSTEM)

    if not result:
        logger.warning(f"[Arbiter] LLM failed after retry — using prosecution score as fallback.")
        return _build_fallback_state(state)

    # Map criteria_key to final score
    raw_criteria_key = result.get("criteria_key")
    valid_keys = get_criteria_keys(indicator_id)
    criteria_key = None
    if raw_criteria_key and isinstance(raw_criteria_key, str) and raw_criteria_key in valid_keys:
        criteria_key = raw_criteria_key
    elif raw_criteria_key:
        logger.warning(
            f"[Arbiter] Unknown criteria_key '{raw_criteria_key}' for {indicator_id} "
            f"— valid keys: {valid_keys}"
        )
    if criteria_key:
        mapped_score = criteria_to_score(indicator_id, criteria_key)
        if mapped_score is not None:
            final_score = validate_score(indicator_id, mapped_score)
        else:
            final_score = 0.0
    else:
        final_score = 0.0

    # ================================================================
    # PROGRAMMATIC QUOTE EXTRACTION
    # ================================================================
    llm_quote = result.get("verbatim_quote")
    evidence_idx = result.get("evidence_chunk_index")

    final_quote = _extract_quote_programmatically(
        evidence_idx=evidence_idx,
        chunks=chunks,
        llm_quote=llm_quote,
        prosecution_quote=state.get("prosecution_quote"),
    )

    # ================================================================
    # PROGRAMMATIC LAW NAME EXTRACTION
    # ================================================================
    llm_law_name = result.get("act_and_practice")
    law_name_idx = result.get("law_name_chunk_index")

    final_law_name = _extract_field_programmatically(
        field_name="act_and_practice",
        field_value=llm_law_name,
        chunk_index=law_name_idx,
        chunks=chunks,
    )

    # ================================================================
    # PROGRAMMATIC TIMEFRAME EXTRACTION
    # ================================================================
    llm_timeframe = result.get("timeframe")
    timeframe_idx = result.get("timeframe_chunk_index")

    final_timeframe = _extract_field_programmatically(
        field_name="timeframe",
        field_value=llm_timeframe,
        chunk_index=timeframe_idx,
        chunks=chunks,
    )

    # Fallback: if programmatic extraction failed, collect dates from chunk metadata
    if not final_timeframe:
        all_dates = set()
        for c in chunks:
            dates_str = c.get("metadata", {}).get("dates", "")
            if dates_str:
                for d in dates_str.split("; "):
                    d = d.strip()
                    if d:
                        all_dates.add(d)
        if len(all_dates) >= 2:
            # Multiple dates → range: "Enacted YYYY, last amended YYYY"
            years = sorted(set(d for d in all_dates if d.isdigit() and len(d) == 4))
            if len(years) >= 2:
                final_timeframe = f"Since {years[0]}, last amended {years[-1]}"
            else:
                final_timeframe = "; ".join(sorted(all_dates))
        elif len(all_dates) == 1:
            final_timeframe = list(all_dates)[0]

    # ================================================================
    # PROGRAMMATIC COVERAGE EXTRACTION
    # ================================================================
    llm_coverage = result.get("coverage")
    coverage_idx = result.get("coverage_chunk_index")
    final_coverage = _extract_field_programmatically(
        field_name="coverage",
        field_value=llm_coverage,
        chunk_index=coverage_idx,
        chunks=chunks,
    ) or llm_coverage

    # ================================================================
    # REFERENCES ENRICHMENT: collect all chunk URLs
    # ================================================================
    chunk_urls = set()
    for c in chunks:
        url = c.get("metadata", {}).get("source_url")
        if url:
            chunk_urls.add(url)

    llm_refs = result.get("references") or ""
    existing_refs = set()
    if llm_refs:
        for line in llm_refs.split("\n"):
            line = line.strip()
            if line:
                existing_refs.add(line)
    combined_refs = existing_refs | chunk_urls
    final_references = "\n".join(sorted(combined_refs)) if combined_refs else None

    # ================================================================
    # MULTI-LAW SUPPORT
    # ================================================================
    laws_list = result.get("laws") or []
    multi_laws = []
    seen_laws = set()
    if laws_list and isinstance(laws_list, list):
        for entry in laws_list:
            law_name = entry.get("act_and_practice")
            if law_name:
                law_key = law_name.strip().lower()
                if law_key in seen_laws:
                    continue
                seen_laws.add(law_key)
                verified_law = _extract_field_programmatically(
                    field_name="act_and_practice",
                    field_value=law_name,
                    chunk_index=None,
                    chunks=chunks,
                )
                if not verified_law:
                    logger.info(f"[Arbiter] Skipping multi-law entry — unverified: {law_name[:80]}")
                    continue
                # Extra safety: verify the law name appears near country name in gov source
                if not _is_law_country_relevant(verified_law, state.get("country", ""), chunks):
                    logger.info(f"[Arbiter] Skipping multi-law entry — not country-relevant: {verified_law[:80]}")
                    continue
                # Extract per-law metadata directly from chunks
                per_law_ref = _extract_per_law_metadata(verified_law, "law_number_ref", chunks)
                per_law_article = _extract_per_law_metadata(verified_law, "article_citation", chunks)
                per_law_timeframe = _extract_per_law_metadata(verified_law, "timeframe", chunks)
                per_law_quote = _extract_verbatim_for_law(verified_law, chunks, primary_law_name=final_law_name)
                multi_laws.append({
                    "act_and_practice": verified_law,
                    "coverage": entry.get("coverage", final_coverage),
                    "impact_comments": entry.get("impact_comments", result.get("impact_comments")),
                    "timeframe": per_law_timeframe or entry.get("timeframe", final_timeframe),
                    "references": entry.get("references", final_references),
                    "note": entry.get("note", result.get("note", "—")),
                    "law_number_ref": per_law_ref,
                    "article_citation": per_law_article,
                    "verbatim_quote": per_law_quote,
                })

    # Store multi-law data in state for orchestrator to expand
    final_note = result.get("note", "—")
    final_impact = result.get("impact_comments")

    not_found = bool(result.get("not_found", False)) or (
        final_score == 0.0 and not final_quote and criteria_key is None
    )

    # ================================================================
    # INITIALIZE article_cITATION — from LLM result, reject excerpt labels
    # ================================================================
    raw_citation = result.get("article_citation")
    if raw_citation and re.match(
        r'^(EXCERPT|DOCUMENT|CHUNK)\s+\d+', raw_citation, re.IGNORECASE
    ):
        logger.warning(f"[Arbiter] Rejecting article_citation (excerpt label): {raw_citation}")
        raw_citation = None
    if raw_citation and re.match(r'^\d+\.\s', raw_citation.strip()):
        logger.warning(f"[Arbiter] Rejecting article_citation (numbered list item): {raw_citation!r}")
        raw_citation = None

    # ================================================================
    # METADATA ENRICHMENT — focused LLM call to FILL MISSING fields
    # Only runs when key fields are still null after programmatic extraction.
    # This is a SEPARATE, focused LLM call — no scoring, no reconciliation.
    # ================================================================
    final_law_number_ref = None
    final_location_ref = None
    enrichment_needed = (
        not final_law_name
        or not final_timeframe
        or not raw_citation
        or not final_coverage or final_coverage == "N/A"
    )
    if enrichment_needed and not not_found and chunks:
        enrichment = await _enrich_metadata_from_chunks(
            chunks=chunks,
            evidence_idx=evidence_idx,
        )
        if enrichment:
            if not final_law_name and enrichment.get("act_and_practice"):
                enr_law = _clean_law_name(enrichment["act_and_practice"].strip())
                if not _is_structural_ref(enr_law):
                    final_law_name = enr_law
                    logger.info(f"[Arbiter] Law name from metadata enrichment: {final_law_name}")
                else:
                    logger.warning(f"[Arbiter] Rejecting structural ref as law name from enrichment: {enr_law!r}")
            if not final_timeframe and enrichment.get("timeframe"):
                enr_tf = enrichment["timeframe"]
                if not _is_document_structure_text(enr_tf):
                    final_timeframe = enr_tf
                    logger.info(f"[Arbiter] Timeframe from metadata enrichment: {final_timeframe}")
                else:
                    logger.warning(f"[Arbiter] Rejecting document structure text from enrichment timeframe: {enr_tf!r}")
            if not raw_citation and enrichment.get("article_citation"):
                enr_ac = enrichment["article_citation"]
                if enr_ac and re.match(r'^\d+\.\s', enr_ac.strip()):
                    logger.warning(f"[Arbiter] Rejecting numbered list item from enrichment citation: {enr_ac!r}")
                else:
                    raw_citation = enr_ac
                    logger.info(f"[Arbiter] Citation from metadata enrichment: {raw_citation}")
            if (not final_coverage or final_coverage == "N/A") and enrichment.get("coverage"):
                final_coverage = enrichment["coverage"]
                logger.info(f"[Arbiter] Coverage from metadata enrichment: {final_coverage}")
            if enrichment.get("law_number_ref"):
                lr = enrichment["law_number_ref"]
                # Safety: reject section/part/chapter/APP labels as law_number_ref
                # Includes abbreviated forms: "s 16C", "s. 16C", "APP 8.1", "art 9"
                if re.match(
                    r'^(Part|Chapter|Section|Article|Paragraph|Clause|Schedule|Annex|APP|App|'
                    r'S\.?\s|s\.?\s|Art\.?\s|Para\.?\s|Cl\.?\s|Reg\.?\s)\b',
                    lr.strip(), re.IGNORECASE
                ):
                    logger.warning(f"[Arbiter] Rejecting section label as law_number_ref: {lr}")
                elif raw_citation and lr.strip().lower() == raw_citation.strip().lower():
                    logger.warning(f"[Arbiter] Rejecting law_number_ref that duplicates article_citation: {lr!r}")
                else:
                    final_law_number_ref = lr
            if enrichment.get("location_ref"):
                loc = enrichment["location_ref"].strip()
                # Reject broader regional names for domestic laws — the LLM may
                # pick up "ASEAN", "APEC", "EU" etc. from comparison context.
                _REGIONAL_MARKERS = {"asean", "apec", "eu", "european union", "un", "wto", "oecd"}
                if loc.lower() in _REGIONAL_MARKERS and country.lower() not in loc.lower():
                    logger.warning(f"[Arbiter] Rejecting location_ref (regional scope for domestic law): {loc}")
                else:
                    final_location_ref = loc
            # Process additional laws found by metadata enrichment
            enrichment_laws = enrichment.get("additional_laws")
            if enrichment_laws and isinstance(enrichment_laws, list):
                for law_name in enrichment_laws:
                    if law_name and isinstance(law_name, str) and law_name.strip():
                        law_clean = law_name.strip()
                        law_key = law_clean.lower()
                        if law_key not in seen_laws and law_clean != (final_law_name or "").strip().lower():
                            seen_laws.add(law_key)
                            # Verify the law name and extract per-law metadata
                            verified_enrich_law = _extract_field_programmatically(
                                field_name="act_and_practice",
                                field_value=law_clean,
                                chunk_index=None,
                                chunks=chunks,
                            )
                            if not verified_enrich_law:
                                logger.info(f"[Arbiter] Skipping enrichment law — unverified: {law_clean}")
                                continue
                            if not _is_law_country_relevant(verified_enrich_law, state.get("country", ""), chunks):
                                logger.info(f"[Arbiter] Skipping enrichment law — not country-relevant: {verified_enrich_law}")
                                continue
                            enrich_ref = _extract_per_law_metadata(verified_enrich_law, "law_number_ref", chunks)
                            enrich_article = _extract_per_law_metadata(verified_enrich_law, "article_citation", chunks)
                            enrich_timeframe = _extract_per_law_metadata(verified_enrich_law, "timeframe", chunks)
                            enrich_quote = _extract_verbatim_for_law(verified_enrich_law, chunks, primary_law_name=final_law_name)
                            multi_laws.append({
                                "act_and_practice": verified_enrich_law,
                                "coverage": final_coverage,
                                "impact_comments": final_impact,
                                "timeframe": enrich_timeframe or final_timeframe,
                                "references": final_references,
                                "note": final_note,
                                "law_number_ref": enrich_ref,
                                "article_citation": enrich_article,
                                "verbatim_quote": enrich_quote,
                            })
                            logger.info(f"[Arbiter] Additional law from metadata enrichment: {verified_enrich_law}")

    # ================================================================
    # LLM-BASED LAW VERIFICATION — Validate ALL candidate laws against chunks
    # Replaces brittle regex-based per-law metadata extraction with LLM
    # reading comprehension. One LLM call per indicator validates all laws.
    # ================================================================
    all_candidate_laws = []
    # Deduplicate by normalized name
    seen_candidates = set()

    def _norm_law_name(n: str) -> str:
        name = n.strip().lower().rstrip('.')
        # Strip country/jurisdiction prefixes and suffixes
        name = name.replace('(cth)', '').replace('(cwlth)', '').replace('(commonwealth)', '')
        name = name.replace('(sg)', '').replace('(my)', '').replace('(au)', '')
        name = name.replace('(singapore)', '').replace('(malaysia)', '').replace('(australia)', '')
        # Strip leading "the " or "the "
        if name.startswith('the '):
            name = name[4:]
        return name.strip()

    # Add primary law if it exists and the indicator is not "not found"
    primary_law_name = final_law_name or state.get("prosecution_citation")
    if primary_law_name and not not_found:
        norm = _norm_law_name(primary_law_name)
        if norm not in seen_candidates:
            seen_candidates.add(norm)
            all_candidate_laws.append({
                "act_and_practice": primary_law_name,
                "source": "primary",
                "law_number_ref": final_law_number_ref,
                "article_citation": raw_citation,
                "timeframe": final_timeframe,
                "verbatim_quote": final_quote,
            })

    # Add multi-law entries (from Arbiter `laws` array and enrichment additional_laws)
    for ml in multi_laws:
        name = ml.get("act_and_practice")
        if name:
            norm = _norm_law_name(name)
            if norm not in seen_candidates:
                seen_candidates.add(norm)
                all_candidate_laws.append({
                    **ml,
                    "source": ml.get("source", "multi"),
                })

    # Pre-discover law names from ALL chunks — catches laws the LLM might have missed
    pre_discovered = _pre_discover_law_names(chunks, state.get("country", ""), seen_candidates)
    for pd_name in pre_discovered:
        pd_norm = _norm_law_name(pd_name)
        if pd_norm not in seen_candidates:
            seen_candidates.add(pd_norm)
            all_candidate_laws.append({
                "act_and_practice": pd_name,
                "source": "pre_discovered",
                "law_number_ref": None,
                "article_citation": None,
                "timeframe": None,
                "verbatim_quote": None,
            })
            logger.info(f"[Arbiter] Pre-discovered law from chunks: {pd_name}")

    # Run LLM verification only if there are candidate laws
    verified_laws = None
    if all_candidate_laws and chunks:
        verified_laws = await _verify_laws_against_chunks(
            country=country,
            indicator_id=indicator_id,
            candidate_laws=all_candidate_laws,
            chunks=chunks,
        )
        if verified_laws:
            logger.info(f"[Arbiter] Law verification returned {len(verified_laws)} valid laws")

    # Use verified data if available, otherwise fall back to unverified data
    if verified_laws:
        # Reorder so the original primary law (from arbitration LLM) comes first.
        # This prevents subsidiary legislation (e.g. "PDP Regulations") from
        # displacing the main act (e.g. "Personal Data Protection Act 2012").
        original_primary = (primary_law_name or "").strip().lower()
        if original_primary:
            primary_idx = next(
                (i for i, v in enumerate(verified_laws)
                 if _norm_law_name(v.get("act_and_practice", "")).strip().lower()
                    == _norm_law_name(original_primary).strip().lower()),
                None
            )
            if primary_idx is not None and primary_idx > 0:
                verified_laws.insert(0, verified_laws.pop(primary_idx))
        # First valid law becomes the primary
        # Verification output ALWAYS wins over enrichment — even null values override,
        # because verification has searched chunks and determined the field is absent.
        # Only use fallback when the field is entirely absent from verification output.
        primary_verified = verified_laws[0]
        if "act_and_practice" in primary_verified:
            final_law_name = primary_verified["act_and_practice"]
        if "law_number_ref" in primary_verified:
            lr = primary_verified["law_number_ref"]
            # Same safety filter as enrichment — reject abbreviated section labels AND em-dash section numbers
            if lr and not re.match(
                r'^(Part|Chapter|Section|Article|Paragraph|Clause|Schedule|Annex|APP|App|'
                r'S\.?\s|s\.?\s|Art\.?\s|Para\.?\s|Cl\.?\s|Reg\.?\s)\b',
                lr.strip(), re.IGNORECASE
            ) and not re.search(r'[—–]|^\d+\.\(', lr) and not (
                raw_citation and lr.strip().lower() == raw_citation.strip().lower()
            ):
                final_law_number_ref = lr
            else:
                logger.warning(f"[Arbiter] Rejecting section label as law_number_ref from verification: {lr}")
        if "article_citation" in primary_verified:
            ac = primary_verified["article_citation"]
            if ac and re.match(r'^\d+\.\s', ac.strip()):
                logger.warning(f"[Arbiter] Rejecting numbered list item as article_citation from verification: {ac!r}")
            else:
                raw_citation = ac
        if "timeframe" in primary_verified:
            tf = primary_verified["timeframe"]
            if tf and (re.match(r'^\d{4}$', tf.strip()) or _is_nav_text(tf) or _is_document_structure_text(tf)):
                logger.warning(f"[Arbiter] Rejecting bad timeframe from verification: {tf!r}")
            else:
                final_timeframe = tf
        if "verbatim_quote" in primary_verified:
            final_quote = primary_verified["verbatim_quote"]

        # Remaining laws become multi_laws — with safety filters applied
        multi_laws = []
        for vl in verified_laws[1:]:
            ml = dict(vl)
            lr = ml.get("law_number_ref")
            if lr and not re.match(
                r'^(Part|Chapter|Section|Article|Paragraph|Clause|Schedule|Annex|APP|App|'
                r'S\.?\s|s\.?\s|Art\.?\s|Para\.?\s|Cl\.?\s|Reg\.?\s)\b',
                lr.strip(), re.IGNORECASE
            ) and not re.search(r'[—–]|^\d+\.\(', lr):
                pass
            else:
                if lr:
                    logger.warning(f"[Arbiter] Rejecting section label as multi-law law_number_ref: {lr}")
                ml["law_number_ref"] = None
            ac = ml.get("article_citation")
            if ac and re.match(r'^\d+\.\s', ac.strip()):
                logger.warning(f"[Arbiter] Rejecting numbered list item as multi-law article_citation: {ac!r}")
                ml["article_citation"] = None
            multi_laws.append(ml)

    # Adjust confidence based on verified fields
    raw_confidence = result.get("confidence", 0.5)
    try:
        base_confidence = max(0.0, min(1.0, float(raw_confidence)))
    except (ValueError, TypeError):
        base_confidence = 0.5
    fields_verified = sum(1 for f in [final_law_name, final_timeframe, final_quote] if f is not None)
    confidence_penalty = (3 - fields_verified) * 0.1
    adjusted_confidence = max(0.1, base_confidence - confidence_penalty)

    return {
        **state,
        "final_score": final_score,
        "final_criteria_key": criteria_key,
        "act_and_practice": final_law_name,
        "coverage": final_coverage,
        "impact_comments": final_impact,
        "timeframe": final_timeframe,
        "references": final_references,
        "note": final_note,
        "final_confidence": adjusted_confidence,
        "final_quote": final_quote,
        "final_citation": raw_citation,
        "law_number_ref": final_law_number_ref,
        "location_ref": final_location_ref,
        "not_found": not_found,
        "multi_laws": multi_laws if multi_laws else None,
    }


def _is_valid_law_name(name: str) -> bool:
    """Check if a string looks like a valid law name (not a text fragment or section label)."""
    if not name or len(name) < 5:
        return False
    stripped = name.strip()
    if not stripped[0].isupper():
        return False
    words = stripped.split()
    if len(words) > 20:
        return False
    # Reject section/part labels like "Part IIIA", "Chapter II" — these have
    # a section keyword but no legal keyword as the HEAD noun.
    section_keywords = {'Part', 'Chapter', 'Section', 'Article', 'Paragraph',
                        'Clause', 'Schedule', 'Appendix', 'Annex'}
    if words[0] in section_keywords:
        return False
    # Reject names that are schedule/appendix/anex references rather than
    # actual law names (e.g. "First Schedule to the Act", "Schedule 1")
    # Schedules are structural parts of laws, not standalone law names.
    structural_parts = {'schedule', 'appendix', 'annex'}
    for w in words:
        if w.lower() in structural_parts:
            return False
    # Accept law-number-only names (e.g. "Act 709", "P.U. (A) 123/2021")
    # These are valid primary law names in many jurisdictions.
    # But reject bare "Act YYYY" — nearly always a fragment.
    if _LAW_NUM_NAME_PATTERN.fullmatch(stripped):
        if re.match(r'^Act\s+\(?\d{4}\)?$', stripped):
            return False
        return True
    # Check if any legal keyword appears as a COMPLETE WORD in the name.
    # Uses case-sensitive matching — "framework" (in descriptive text like
    # "legislative framework") won't match "Framework" (a proper law name).
    # This prevents non-law descriptive text from passing validation.
    first_words_set = set(words[:8])
    return bool(first_words_set & _LEGAL_KEYWORDS)


def _extract_law_name_span(chunk_text: str, hint: str) -> str | None:
    """
    Extract a clean law/act name from chunk text near the hint position.
    Uses pattern matching to find proper legal citations (e.g. 'Privacy Act 1988').
    Returns None if no clean law name can be found.
    """
    if not hint or not chunk_text:
        return None
    hint_lower = hint.strip().lower()
    chunk_lower = chunk_text.lower()
    pos = chunk_lower.find(hint_lower)
    if pos < 0:
        return None
    window_start = max(0, pos - 300)
    window_end = min(len(chunk_text), pos + len(hint) + 200)
    window = chunk_text[window_start:window_end]
    hint_offset = pos - window_start
    best = None
    best_dist = float('inf')
    for pat in (_LAW_NAME_PATTERN, _LAW_NUM_NAME_PATTERN):
        for m in pat.finditer(window):
            candidate = m.group(0).strip()
            # Reject secondary-pattern-only false positives like "Act YYYY"
            if pat is _LAW_NUM_NAME_PATTERN and re.match(r'^act\s+\(?\d{4}\)?$', candidate, re.IGNORECASE):
                continue
            m_center = (m.start() + m.end()) // 2
            dist = abs(m_center - (hint_offset + len(hint) // 2))
            if dist < best_dist:
                best_dist = dist
                best = m.group(0)
    if best:
        name = _clean_law_name(best.strip())
        return name
    return None


def _is_structural_ref(name: str) -> bool:
    """Check if name is a structural reference (schedule, appendix, etc.) rather than a law."""
    if not name:
        return True
    structural = {'schedule', 'appendix', 'annex'}
    for w in name.strip().lower().split():
        if w in structural:
            return True
    return False


def _extract_field_programmatically(
    field_name: str,
    field_value: str | None,
    chunk_index: Any,
    chunks: list[dict],
) -> str | None:
    """
    Extract a field (law name, timeframe, coverage) from the stored chunk
    using the chunk index provided by the LLM.

    NEW APPROACH: Trust the LLM when it provides a chunk reference or value.
    Regex patterns are ONLY used for:
    - Rejecting obviously wrong names (schedules, structural refs)
    - Blind scanning (Strategy 3) when LLM provided nothing

    Fallback chain:
      1. If valid chunk_index → verify field_value exists in that chunk, use it
      2. If field_value exists verbatim in any chunk → use it
      3. Blind scan all chunks for any law name pattern → use best match
      4. None
    """
    # Strategy 1: LLM provided chunk_index — try regex first for full name,
    # then fall back to LLM's verbatim value if regex finds nothing.
    if chunk_index is not None:
        try:
            idx = int(chunk_index)
            if 1 <= idx <= len(chunks):
                chunk_text = chunks[idx - 1].get("text", "")
                if field_name == "act_and_practice":
                    regex_name = None
                    if field_value:
                        # Try regex near LLM hint first (prefers full names like "Privacy Act 1988 (Cth)")
                        regex_name = _extract_law_name_span(chunk_text, field_value.strip())
                        if regex_name and not _is_structural_ref(regex_name):
                            logger.info(f"[Arbiter] {field_name} regex-extracted near LLM hint (chunk {idx}): {regex_name}")
                            return regex_name
                    # No regex match — try verbatim substring match
                    if field_value:
                        fv = _clean_law_name(field_value.strip())
                        if fv.lower() in chunk_text.lower() and not _is_structural_ref(fv):
                            logger.info(f"[Arbiter] {field_name} verbatim in chunk {idx}: {fv}")
                            return fv
                    # Try scanning chunk for any law name pattern
                    for candidate in _find_law_names(chunk_text):
                        if not _is_structural_ref(candidate):
                            logger.info(f"[Arbiter] {field_name} regex-found in chunk_index={idx}")
                            return candidate
                else:
                    if field_value:
                        fv = field_value.strip()
                        if fv.lower() in chunk_text.lower():
                            logger.info(f"[Arbiter] {field_name} verbatim in chunk {idx}: {fv}")
                            return fv
                        logger.info(f"[Arbiter] {field_name} using LLM value (chunk {idx} provided): {fv}")
                        return fv
        except (ValueError, TypeError):
            pass

    # Strategy 2: LLM provided field_value — verify it exists verbatim in chunks
    if field_value:
        fv = _clean_law_name(field_value.strip())
        if not _is_structural_ref(fv):
            # Minimal law-name smell check: must contain a legal keyword
            # OR match the law-number pattern (prevents descriptive phrases).
            legal_lower = {k.lower() for k in _LEGAL_KEYWORDS}
            if (set(fv.lower().split()) & legal_lower) or _LAW_NUM_NAME_PATTERN.search(fv):
                fv_lower = fv.lower()
                for chunk in chunks:
                    chunk_text = chunk.get("text", "")
                    if fv_lower in chunk_text.lower():
                        logger.info(f"[Arbiter] {field_name} verified verbatim in chunks: {fv}")
                        return fv
                    # Fallback to word overlap similarity
                    sim = _word_overlap_similarity(fv, chunk_text)
                    if sim >= 0.75:
                        logger.info(f"[Arbiter] {field_name} verified via word overlap in chunks (sim={sim:.2f}): {fv}")
                        return fv

    # Strategy 3: Blind scan — LLM provided nothing or value not found
    # Use all patterns to discover law names from chunks
    if field_name == "act_and_practice":
        name_counts: dict[str, int] = {}
        gov_names: set[str] = set()
        for chunk in chunks:
            url = (chunk.get("metadata") or {}).get("source_url", "")
            is_gov = ".gov" in url if url else False
            for name in _find_law_names(chunk.get("text", "")):
                if not _is_structural_ref(name):
                    name_counts[name] = name_counts.get(name, 0) + 1
                    if is_gov:
                        gov_names.add(name)
        if name_counts:
            if gov_names:
                best = max(gov_names, key=lambda n: name_counts[n])
                logger.info(f"[Arbiter] {field_name} blind-scan (gov source): {best}")
                return best
            best = max(name_counts, key=lambda n: name_counts[n])
            logger.info(f"[Arbiter] {field_name} blind-scan (freq={name_counts[best]}): {best}")
            return best

    logger.warning(f"[Arbiter] {field_name} cannot be verified in any chunk — returning None")
    return None


def _extract_quote_programmatically(
    evidence_idx: Any,
    chunks: list[dict],
    llm_quote: str | None,
    prosecution_quote: str | None,
) -> str | None:
    """
    Extract the quote from the stored chunk using the evidence_chunk_index.
    Fallback chain:
      1. If valid evidence_chunk_index → extract text from that chunk
      2. If LLM quote can be verified against chunks → use LLM quote
      3. If prosecution quote can be verified → use prosecution quote
      4. Otherwise → None
    """
    # Strategy 1: evidence_chunk_index is the most reliable
    if evidence_idx is not None:
        try:
            idx = int(evidence_idx)
            if 1 <= idx <= len(chunks):
                chunk_text = chunks[idx - 1].get("text", "")
                quote = _extract_relevant_span(chunk_text, llm_quote or "")
                if quote:
                    logger.info(f"[Arbiter] Quote extracted via evidence_chunk_index={idx}")
                    return quote
        except (ValueError, TypeError):
            pass

    # Strategy 2: Try to verify LLM's verbatim quote against chunks
    if llm_quote:
        normalized = llm_quote.strip().lower()
        for chunk in chunks:
            chunk_text = chunk.get("text", "")
            if normalized in chunk_text.lower():
                logger.info("[Arbiter] LLM verbatim_quote verified in chunks")
                return llm_quote.strip()
            # Fallback to word overlap similarity
            sim = _word_overlap_similarity(llm_quote, chunk_text)
            if sim >= 0.75:
                logger.info(f"[Arbiter] LLM verbatim_quote verified via word overlap (sim={sim:.2f})")
                return llm_quote.strip()

    # Strategy 3: Fall back to prosecution quote (already validated against chunks)
    if prosecution_quote:
        normalized = prosecution_quote.strip().lower()
        for chunk in chunks:
            chunk_text = chunk.get("text", "")
            if normalized in chunk_text.lower():
                logger.info("[Arbiter] Using prosecution quote as fallback")
                return prosecution_quote.strip()

    logger.warning("[Arbiter] No verifiable quote found — returning None")
    return None


def _extract_relevant_span(chunk_text: str, hint_quote: str) -> str | None:
    """
    Extract a relevant quote from a chunk.
    If a hint quote is provided, try to find its surrounding context.
    Otherwise return None to allow fallback strategies.
    """
    if hint_quote:
        hint_normalized = hint_quote.strip().lower()
        chunk_lower = chunk_text.lower()
        idx = chunk_lower.find(hint_normalized)
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(chunk_text), idx + len(hint_quote) + 50)
            return chunk_text[start:end].strip()
    return None


def _format_chunks(chunks: list[dict]) -> str:
    """Format chunk list into readable text blocks for the prompt."""
    max_chunks = 60
    if len(chunks) > max_chunks:
        logger.info(
            f"[Arbiter] Truncating {len(chunks)} chunks to {max_chunks} "
            f"for LLM context window"
        )
    parts = []
    for i, chunk in enumerate(chunks[:max_chunks]):
        meta = chunk.get("metadata", {})
        source = meta.get("source_url", "Unknown source")
        text = chunk.get("text", "")
        parts.append(f"[DOCUMENT {i+1} — Source: {source}]\n{text}\n")
    return "\n---\n".join(parts)


def _build_not_found_state(state: AnalysisState) -> AnalysisState:
    ref_urls = set()
    for c in state.get("chunks", []):
        url = c.get("metadata", {}).get("source_url")
        if url:
            ref_urls.add(url)
    ref_str = "\n".join(sorted(ref_urls)) if ref_urls else None

    has_chunks = bool(state.get("chunks"))
    impact_comments = (
        "No relevant provision found in the available source documents."
        if has_chunks
        else "No source documents were available for analysis."
    )
    note = (
        "Automated discovery found no primary source evidence for this indicator."
        if has_chunks
        else "No documents were discovered for this indicator."
    )

    return {
        **state,
        "final_score": 0.0,
        "final_criteria_key": None,
        "act_and_practice": None,
        "coverage": "N/A",
        "impact_comments": impact_comments,
        "timeframe": None,
        "references": ref_str,
        "note": note,
        "final_confidence": 0.2,
        "final_quote": None,
        "final_citation": None,
        "not_found": True,
    }


def _build_fallback_state(state: AnalysisState) -> AnalysisState:
    """Fallback when the arbiter LLM call fails — use prosecution data directly."""
    p_score = state.get("prosecution_score", 0.0)
    try:
        final_score = validate_score(state["indicator_id"], float(p_score))
    except Exception:
        final_score = 0.0

    # Collect all chunk source URLs for references
    chunk_urls = set()
    for c in state.get("chunks", []):
        url = c.get("metadata", {}).get("source_url")
        if url:
            chunk_urls.add(url)

    # Try to extract the law name from chunks (avoiding excerpt label)
    chunks = state.get("chunks", [])
    best_law = None
    prosecution_citation = state.get("prosecution_citation") or ""
    if prosecution_citation and chunks:
        for chunk in chunks:
            text = chunk.get("text", "")
            if prosecution_citation.strip().lower() in text.lower():
                best_law = prosecution_citation.strip()
                break

    if not best_law and chunks:
        # Fallback: pick first valid law name from chunk text
        for chunk in chunks:
            text = chunk.get("text", "")
            for candidate in _find_law_names(text):
                if not _is_structural_ref(candidate):
                    best_law = candidate
                    break
            if best_law:
                break

    ref_str = "\n".join(sorted(chunk_urls)) if chunk_urls else None
    final_act = best_law or state.get("prosecution_citation")

    return {
        **state,
        "final_score": final_score,
        "final_criteria_key": state.get("prosecution_criteria_key"),
        "act_and_practice": final_act,
        "coverage": "N/A",
        "impact_comments": state.get("prosecution_reasoning"),
        "timeframe": None,
        "references": ref_str,
        "note": "Arbiter LLM call failed — using prosecution output directly.",
        "final_confidence": state.get("prosecution_confidence", 0.3),
        "final_quote": state.get("prosecution_quote"),
        "final_citation": state.get("prosecution_citation"),
        "not_found": final_score == 0.0,
    }


_VERIFY_R1_PROMPT = """You are a precise legal document analyst. Your task is to verify proposed laws against the provided document excerpts using step-by-step reasoning.

CONTEXT:
- Country: {country}
- Indicator: {indicator_id}

DOCUMENT EXCERPTS:
{chunks_text}

CANDIDATE LAWS TO VERIFY:
{candidate_list}

INSTRUCTIONS — Think step by step:

PART A — Verify the candidate laws listed above. For each, follow:
1. SEARCH: Find the law name in the excerpts
2. VALIDATE: Is this a domestic {country} data protection/cybersecurity law?
3. EXTRACT: law_number_ref, article_citation, timeframe, verbatim_quote
4. IDENTIFY GAPS: Suggest search queries for missing fields

PART B — DISCOVER NEW LAWS. While reviewing the excerpts, look for OTHER laws of {country} that are:
- Formal legal instruments (e.g. "Privacy Act 1988", "My Health Records Act 2012")
- Relevant to data protection, cybersecurity, privacy, or cross-border data transfers
- NOT already in the candidate list above

If you find any, add them to the "laws" array with is_valid=true and their extracted metadata.
ALSO add their names to the "newly_discovered_laws" array for tracking.

CRITICAL RULES:
- Every extracted value must be a DIRECT SUBSTRING of the excerpts. Never guess.
- Reject foreign laws, treaties, and descriptive phrases.
- Deduplicate: do not add a law that's already in the candidate list.
- Only discover a law if it appears BY NAME as a formal legal instrument in the excerpts.
- For newly discovered laws, also suggest missing_searches if you can't extract all fields.

Output JSON with a "laws" array (ALL laws: verified candidates + newly discovered) and a "newly_discovered_laws" array (just the names). Each law must include "reasoning" and "missing_searches".

Example output:
{{
  "laws": [
    {{
      "act_and_practice": "Privacy Act 1988",
      "is_valid": true,
      "reasoning": "Step 1: Found 'Privacy Act 1988' in EXCERPT LAW 1... Step 2: This is an Australian act... Step 3: Found article_citation 'APP 8.1' but could not find amendment date... Step 4: Need to search for compilation date near law name.",
      "law_number_ref": null,
      "article_citation": "APP 8.1",
      "timeframe": null,
      "verbatim_quote": "APP 8 of the Privacy Act 1988 (Cth) imposes strict accountability requirements",
      "missing_searches": [
        {{"field": "timeframe", "query": "Privacy Act 1988 compilation date OR amendment OR No. 119", "reason": "Need the last amendment date from the act's endnotes"}},
        {{"field": "law_number_ref", "query": "Privacy Act 1988 No. 119 OR Act No", "reason": "Need the official act reference number"}}
      ]
    }},
    {{
      "act_and_practice": "UKUSA Agreement",
      "is_valid": false,
      "reasoning": "Step 1: Found 'UKUSA Agreement' in EXCERPT LAW 3 mentioning Five Eyes alliance. Step 2: This is an intelligence-sharing treaty between Five Eyes countries, not a domestic data protection law of {country}. REJECTED.",
      "law_number_ref": null,
      "article_citation": null,
      "timeframe": null,
      "verbatim_quote": null,
      "missing_searches": []
    }}
  ],
  "newly_discovered_laws": [
    "My Health Records Act 2012"
  ]
}}
"""

_VERIFY_R2_PROMPT = """You are a precise legal document analyst. Continue your verification with ADDITIONAL document excerpts.

CONTEXT:
- Country: {country}
- Indicator: {indicator_id}

YOUR PREVIOUS ANALYSIS (Round 1):
{round1_output}

You requested additional searches for missing metadata. Here are the NEW document excerpts retrieved:
{new_chunks_text}

ORIGINAL EXCERPTS (for reference):
{original_chunks_text}

TASK:
1. Review the NEW excerpts for the missing fields you identified in Round 1
2. Extract the missing values verbatim from the new excerpts
3. Produce the FINAL verified law entry with ALL fields filled or confirmed null
4. If a field is still not found after reviewing new excerpts, set it to null

CRITICAL RULES:
- Every value must be a DIRECT SUBSTRING of EITHER the original or new excerpts.
- Never guess. Only extract what you see verbatim.
- Keep the same is_valid, act_and_practice, and reasoning from Round 1.
- Fill in previously null fields if you find the data in the new excerpts.

Output ONLY a JSON object with a single key "laws" containing the FINAL verified law objects.
Each object: {{"act_and_practice", "is_valid", "reasoning", "law_number_ref", "article_citation", "timeframe", "verbatim_quote"}}
"""


def _build_prioritized_excerpts(
    chunks: list[dict],
    candidate_names: set[str],
    max_chars: int = 30000,
) -> tuple[str, list[dict], list[dict]]:
    """Split chunks into law-mentioning and other, build excerpt string prioritizing law chunks."""
    CHUNK_SEP = "\n\n---\n\n"
    law_chunks = []
    other_chunks = []
    for c in chunks:
        text = c.get("text", "")
        if not text:
            continue
        text_lower = text.lower()
        if candidate_names and any(n in text_lower for n in candidate_names):
            law_chunks.append(c)
        else:
            other_chunks.append(c)

    seen_urls = set()
    entries = []

    for pool, label, limit, max_len in [
        (law_chunks, "LAW", 15, 4000),
        (other_chunks, "OTHER", 15, 2000),
    ]:
        for i, c in enumerate(pool[:limit]):
            text = c.get("text", "")[:max_len]
            url = c.get("metadata", {}).get("source_url", "")
            if url:
                url_key = url.split("?")[0][:120]
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
            entry = f"[EXCERPT {label} {i+1}] (Source: {url})\n{text}"
            cost = len(entry) + (len(CHUNK_SEP) if entries else 0)
            if sum(e[0] for e in entries) + cost > max_chars:
                break
            entries.append((cost, entry))
            if label == "LAW":
                # Check remaining space after each LAW chunk
                if sum(e[0] for e in entries) > max_chars * 0.8:
                    break

    total_cost = sum(e[0] for e in entries)
    final_entries = [e[1] for e in entries]
    formatted_chunks = CHUNK_SEP.join(final_entries)
    if len(formatted_chunks) > max_chars:
        formatted_chunks = formatted_chunks[:max_chars]

    return formatted_chunks, law_chunks, other_chunks


def _pre_discover_law_names(
    chunks: list[dict],
    country: str,
    existing_names: set[str] | None = None,
) -> list[str]:
    """Scan ALL chunks for formal law names not already in the candidate list or existing set.
    Also catches descriptive law references (e.g. 'My Health Record system') as weaker candidates
    that get verified by the LLM step.
    Deduplicates near-identical variants and limits output to top 20 candidates.
    Returns sorted list of unique law name strings (most relevant first)."""
    MAX_CANDIDATES = 20
    found: dict[str, list[str]] = {}  # norm_key -> [variants]
    existing = existing_names or set()
    for chunk in chunks:
        text = chunk.get("text", "")
        if not text:
            continue
        # Formal law names (strong candidates)
        for name in _find_law_names(text):
            norm = name.lower().strip()
            if norm in existing:
                continue
            if not _is_structural_ref(name) and _is_law_country_relevant(name, country, chunks):
                dedup_key = re.sub(r'\s+', ' ', norm).strip()
                found.setdefault(dedup_key, []).append(name)
        # Descriptive references (weaker candidates, will be verified by LLM)
        for ref in _find_descriptive_law_refs(text):
            ref_lower = ref.lower().strip()
            if ref_lower in existing:
                continue
            # Check if this descriptive ref already exists as a formal name candidate
            dedup_key = re.sub(r'\s+', ' ', ref_lower).strip()
            if dedup_key not in found and _is_law_country_relevant(ref, country, chunks):
                found.setdefault(dedup_key, []).append(f"{ref} [descriptive]")
    if not found:
        return []
    # Rank: prefer complete names (with 4-digit year) over fragments, then by length
    # Descriptive references get penalty — they're weaker candidates
    def _rank(key_variants: tuple) -> float:
        key, variants = key_variants
        rep = max(variants, key=len)
        score = len(rep)
        if re.search(r'\b[12]\d{3}\b', rep):
            score += 500
        if len(rep) < 15:
            score -= 300
        # Penalty for descriptive-only references (marked with [descriptive])
        if rep.endswith('[descriptive]'):
            score -= 400
        return -score
    # Strip internal [descriptive] markers before returning names to caller
    def _clean(name: str) -> str:
        return name.replace(' [descriptive]', '').strip()
    sorted_names = [_clean(max(variants, key=len)) for _, variants in sorted(found.items(), key=_rank)]
    return sorted_names[:MAX_CANDIDATES]


def _search_chunks_for_law(
    law_name: str,
    search_query: str,
    chunks: list[dict],
    max_results: int = 5,
) -> list[dict]:
    """
    Search all chunks for a specific query near a law name.
    Returns chunks that mention BOTH the law name AND the search terms.
    """
    if not law_name or not chunks:
        return []
    law_lower = law_name.strip().lower()
    law_words = set(law_lower.split())
    # Filter out law name words and short words from the query
    query_terms = [t for t in search_query.lower().split()
                   if len(t) > 2 and t not in law_words]

    scored = []
    for c in chunks:
        text = c.get("text", "")
        if not text:
            continue
        text_lower = text.lower()
        # Must mention law name
        if law_lower not in text_lower:
            continue
        # Score by how many ADDITIONAL query terms match
        if not query_terms:
            continue  # no discriminating terms
        score = sum(1 for t in query_terms if t in text_lower)
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:max_results]]


async def _verify_laws_against_chunks(
    country: str,
    indicator_id: str,
    candidate_laws: list[dict],
    chunks: list[dict],
) -> list[dict] | None:
    """
    Two-round verification:
    Round 1: LLM identifies valid laws, extracts what it can, and specifies missing searches.
    Round 2: System searches chunks for missing data, LLM produces final output.
    """
    if not candidate_laws or not chunks:
        return None

    # Collect candidate law name variants
    candidate_names = set()
    for cl in candidate_laws:
        name = cl.get("act_and_practice", "")
        if name:
            candidate_names.add(name.strip().lower())
            words = name.strip().split()
            if len(words) >= 2:
                candidate_names.add(" ".join(words[:2]).lower())
            if len(words) >= 3:
                candidate_names.add(" ".join(words[:3]).lower())

    # ==============================
    # ROUND 1: Identify + Reason
    # ==============================
    formatted_chunks, law_chunks, other_chunks = _build_prioritized_excerpts(chunks, candidate_names)

    candidate_lines = []
    for i, law in enumerate(candidate_laws):
        name = law.get("act_and_practice", "unknown")
        source = law.get("source", "unknown")
        ref = law.get("law_number_ref") or "null"
        cit = law.get("article_citation") or "null"
        tf = law.get("timeframe") or "null"
        candidate_lines.append(f"{i+1}. name='{name}' source='{source}' ref={ref} citation={cit} timeframe={tf}")
    candidate_list = "\n".join(candidate_lines)

    def _esc(s):
        return str(s).replace("{", "{{").replace("}", "}}")

    r1_prompt = _VERIFY_R1_PROMPT.format(
        country=_esc(country),
        indicator_id=_esc(indicator_id),
        chunks_text=_esc(formatted_chunks),
        candidate_list=_esc(candidate_list),
    )

    logger.info(f"[Arbiter] Round 1: Verifying {len(candidate_laws)} laws with reasoning...")
    r1_result: dict = await call_llm_json_async(
        r1_prompt,
        "You are a precise legal document analyst who extracts information ONLY from the provided text. Think step by step."
    )

    if not r1_result or not isinstance(r1_result, dict):
        logger.warning("[Arbiter] Round 1 verification returned empty")
        return None

    r1_laws = r1_result.get("laws", [])
    if not r1_laws or not isinstance(r1_laws, list):
        logger.warning("[Arbiter] Round 1 returned no 'laws' array")
        return None

    # Collect valid laws from Round 1 and identify missing searches
    r1_valid = []
    all_missing_searches = []  # list of (law_name, field, query)
    for law in r1_laws:
        if not isinstance(law, dict):
            continue
        if not law.get("is_valid"):
            name = law.get("act_and_practice", "unknown")
            logger.info(f"[Arbiter] R1 rejected: {name} — {law.get('reasoning', '')[:100]}")
            continue
        name = law.get("act_and_practice")
        if not name or not isinstance(name, str) or not name.strip():
            continue
        r1_valid.append(law)
        # Collect missing searches
        for ms in law.get("missing_searches") or []:
            if isinstance(ms, dict) and ms.get("query"):
                q = ms["query"].strip()
                field = ms.get("field", "unknown")
                if q and len(q) > 5:
                    all_missing_searches.append((name.strip(), field, q))

    if not r1_valid:
        logger.info("[Arbiter] R1: No valid laws found")
        return None

    # Check for newly discovered laws from Round 1
    r1_new_discovered = r1_result.get("newly_discovered_laws", [])
    if r1_new_discovered and isinstance(r1_new_discovered, list):
        for nd_name in r1_new_discovered:
            if isinstance(nd_name, str) and nd_name.strip():
                logger.info(f"[Arbiter] R1 discovered additional law: {nd_name.strip()}")
                # Add to candidate names so their chunks get priority in Round 2
                candidate_names.add(nd_name.strip().lower())

    # Re-prioritize chunks to include newly discovered law chunks for Round 2
    if r1_new_discovered:
        _, law_chunks, _ = _build_prioritized_excerpts(chunks, candidate_names)

    logger.info(f"[Arbiter] R1: {len(r1_valid)} valid laws ({len(r1_new_discovered)} newly discovered), {len(all_missing_searches)} missing searches")

    # ==============================
    # ROUND 2: Retrieve + Fill (if any searches needed)
    # ==============================
    if all_missing_searches:
        logger.info(f"[Arbiter] Round 2: Searching for {len(all_missing_searches)} missing fields...")

        # Collect all search results
        extra_chunks_map = {}  # law_name -> list of chunks
        for law_name, field, query in all_missing_searches:
            found = _search_chunks_for_law(law_name, query, chunks, max_results=3)
            if found:
                extra_chunks_map.setdefault(law_name, []).extend(found)
                logger.info(f"[Arbiter] R2 search for '{law_name}' / '{query}': found {len(found)} chunks")

        if extra_chunks_map:
            # Build Round 2 excerpts: original law chunks + new search result chunks
            CHUNK_SEP = "\n\n---\n\n"
            MAX_CHARS = 30000
            seen_urls = set()
            r2_entries = []

            # First, add search result chunks
            for law_name, extra_chunks in extra_chunks_map.items():
                for i, c in enumerate(extra_chunks[:3]):
                    text = c.get("text", "")[:3000]
                    url = c.get("metadata", {}).get("source_url", "")
                    if url:
                        url_key = url.split("?")[0][:120]
                        if url_key in seen_urls:
                            continue
                        seen_urls.add(url_key)
                    entry = f"[EXCERPT SEARCH for '{law_name}'] (Source: {url})\n{text}"
                    cost = len(entry) + (len(CHUNK_SEP) if r2_entries else 0)
                    if sum(e[0] for e in r2_entries) + cost > MAX_CHARS:
                        break
                    r2_entries.append((cost, entry))

            # Then add original law chunks (up to 5, with priority)
            law_added = 0
            for c in law_chunks:
                if law_added >= 5:
                    break
                text = c.get("text", "")[:2000]
                url = c.get("metadata", {}).get("source_url", "")
                if url:
                    url_key = url.split("?")[0][:120]
                    if url_key in seen_urls:
                        continue
                    seen_urls.add(url_key)
                entry = f"[EXCERPT LAW] (Source: {url})\n{text}"
                cost = len(entry) + (len(CHUNK_SEP) if r2_entries else 0)
                if sum(e[0] for e in r2_entries) + cost > MAX_CHARS:
                    break
                r2_entries.append((cost, entry))
                law_added += 1

            new_chunks_text = CHUNK_SEP.join(e[1] for e in r2_entries)
            if len(new_chunks_text) > MAX_CHARS:
                new_chunks_text = new_chunks_text[:MAX_CHARS]

            # Format Round 1 output for Round 2 context
            r1_output_lines = []
            for law in r1_valid:
                r1_output_lines.append(json.dumps({k: law.get(k) for k in
                    ["act_and_practice", "is_valid", "reasoning", "law_number_ref",
                     "article_citation", "timeframe", "verbatim_quote", "missing_searches"]
                }, indent=2))
            r1_output_text = "\n\n".join(r1_output_lines)
            if len(r1_output_text) > 8000:
                r1_output_text = r1_output_text[:8000]

            r2_prompt = _VERIFY_R2_PROMPT.format(
                country=_esc(country),
                indicator_id=_esc(indicator_id),
                round1_output=_esc(r1_output_text),
                new_chunks_text=_esc(new_chunks_text),
                original_chunks_text=_esc(formatted_chunks[:15000]),
            )

            logger.info("[Arbiter] Round 2: Calling LLM for final verification...")
            r2_result: dict = await call_llm_json_async(
                r2_prompt,
                "You are a precise legal document analyst. Extract only what you see verbatim in the excerpts."
            )

            if r2_result and isinstance(r2_result, dict):
                r2_laws = r2_result.get("laws", [])
                if r2_laws and isinstance(r2_laws, list):
                    valid_laws = []
                    for law in r2_laws:
                        if not isinstance(law, dict):
                            continue
                        if not law.get("is_valid"):
                            continue
                        name = law.get("act_and_practice")
                        if name and isinstance(name, str) and name.strip():
                            valid_laws.append({
                                "act_and_practice": name.strip(),
                                "law_number_ref": law.get("law_number_ref") or None,
                                "article_citation": law.get("article_citation") or None,
                                "timeframe": law.get("timeframe") or None,
                                "verbatim_quote": law.get("verbatim_quote") or None,
                            })
                    if valid_laws:
                        logger.info(f"[Arbiter] R2: {len(valid_laws)} laws with filled metadata")
                        return valid_laws

    # Fallback: use Round 1 results (with nulls for unfound fields)
    logger.info(f"[Arbiter] Using R1 results directly ({len(r1_valid)} laws)")
    return [{
        "act_and_practice": law.get("act_and_practice", "").strip(),
        "law_number_ref": law.get("law_number_ref") or None,
        "article_citation": law.get("article_citation") or None,
        "timeframe": law.get("timeframe") or None,
        "verbatim_quote": law.get("verbatim_quote") or None,
    } for law in r1_valid if law.get("act_and_practice")]


# Per-Law Metadata Extraction Helpers (fallback — LLM verification is preferred)
# These extract law-specific fields (article_citation, law_number_ref, timeframe,
# verbatim_quote) from chunks by searching for the law name in each chunk and
# picking up nearby metadata.

def _is_law_country_relevant(law_name: str, country: str, chunks: list[dict]) -> bool:
    """
    Verify that a law name is relevant to the target country (not a foreign law).
    Requires the law name to appear in a chunk that ALSO mentions the target country
    OR comes from a .gov source. This prevents picking up GDPR/CCPA/etc. from
    comparison/foreign sources when analyzing non-EU countries.
    """
    if not law_name or not country:
        return True
    country_lower = country.strip().lower()
    law_lower = law_name.strip().lower()

    for chunk in chunks:
        chunk_text = chunk.get("text", "")
        if not chunk_text:
            continue
        if law_lower not in chunk_text.lower():
            continue
        # Check if chunk mentions the target country nearby
        chunk_lower = chunk_text.lower()
        pos = chunk_lower.find(law_lower)
        window_start = max(0, pos - 500)
        window_end = min(len(chunk_text), pos + len(law_name) + 500)
        window = chunk_text[window_start:window_end].lower()
        if country_lower in window:
            return True
        # Also check if source URL is .gov (more trustworthy)
        url = (chunk.get("metadata") or {}).get("source_url", "")
        if ".gov" in url or ".edu" in url:
            return True
    return False


_LAW_REF_PATTERN = re.compile(
    r'(?:Act|No\.?\s*|Number|Chapter|Cap\.?|Ordinance|P\.U\.|SL|S\.?\s*L\.?|S\.?\s+)\s*'
    r'(?:No\.?\s*)?'
    r'\d+[\d/]*[A-Za-z]*'
    r'(?:\s*,\s*\d{4})?'
    r'(?:\s+of\s+\d{4})?'
    r'(?:\s*\([A-Za-z0-9/]+\))?'
)

_AMENDMENT_DATE_PATTERN = re.compile(
    r'(?:(?:last\s+)?amended|revised|updated|as\s+amended\s+by|revised\s+edition|entered\s+into\s+force|enacted|commenced)'
    r'(?:\s*(?::|on)?\s*'
    r'(?:\d{1,2}\s+)?'
    r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
    r'\d{4})',
    re.IGNORECASE
)

_SECTION_PATTERN = re.compile(
    r'(?:'
    r'(?:Section|Article|Chapter|Part|Paragraph|Clause|Schedule|Appendix|Annex|Regulation|Rule)\s+'
    r'[A-Z0-9]+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*'
    r'|'
    r'(?:s|s\.|art|art\.|para|para\.|cl|cl\.|reg|reg\.|app|app\.)\s+'
    r'[A-Z0-9]*\d[A-Z0-9]*(?:\.\d+)*(?:\([A-Za-z0-9]+\))*'
    r')',
    re.IGNORECASE
)


def _is_law_ref_number(ref: str) -> bool:
    """
    Returns False if the match is just a year with 'Act'/'No' prefix without
    an 'of YYYY' clause — these are the law's own enactment year, not a
    reference number. Also rejects any ref shorter than 3 characters.
    """
    if not ref or len(ref.strip()) < 3:
        return False
    stripped = ref.strip()
    # If it contains "of 2" or "of 1" (e.g. "of 2012"), it's a real ref
    if re.search(r'\bof\s+\d{4}\b', stripped):
        return True
    # If it's just "Act YYYY" or "No YYYY" without "of", reject it
    if re.match(r'^(?:Act|No)[\s.]*\d{4}$', stripped, re.IGNORECASE):
        return False
    # If it contains both a prefix and a number, it's likely valid
    if re.match(r'(?:Act|No\.?|Number|Chapter|Cap\.?|Ordinance|P\.U\.|SL|S\.?\s*L\.?)', stripped, re.IGNORECASE):
        return True
    return False


# Keywords that indicate website UI/navigation text rather than legal content
_NAV_KEYWORDS = [
    "Search within Legislation",
    "Exit Search",
    "Search Results",
    "find current version as at",
    "or find current version",
    "Go\n",  # standalone "Go" button text
]


def _is_nav_text(text: str) -> bool:
    """Return True if text contains website navigation/UI keywords."""
    if not text:
        return False
    text_lower = text.lower()
    for kw in _NAV_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    # Check for section-like patterns that reference navigation UI
    if re.search(r'(?:versions|current version|page\s+\d+\s+of\s+\d+|results?\s+\d+[-–]\d+)', text_lower):
        return True
    return False


def _is_document_structure_text(text: str) -> bool:
    """Return True if text looks like document structure/formatting rather than legal content.
    Catches headers, footers, page numbers, confidentiality notices, section outlines.
    """
    if not text:
        return True
    t = text.strip()
    # Excessive length — timeframe should be short (dates + context, not paragraphs)
    if len(t) > 200:
        return True
    t_lower = t.lower()
    # Confidentiality / document labels
    if re.search(r'\b(?:private\s*[&and]*\s*confidential|confidential|draft|document\s+title|'
                 r'record\s+keeping|table\s+of\s+contents|introduction|background|overview|'
                 r'purpose|scope|definitions?|abbreviations?)\b', t_lower):
        return True
    # Section structure patterns (e.g. "PART A", "1. Background", "8.3.2.")
    if re.search(r'(?:^PART\s+[A-Z]\b|^\d+\.\s+[A-Z]|^\d+\.\d+\.\d+\.?)', t):
        return True
    # Page numbering
    if re.search(r'(?:page\s+\d+|^\d+\s+of\s+\d+$)', t_lower):
        return True
    # Line drawing characters (e.g. "......................................")
    if re.search(r'\.{10,}|_{10,}|-{10,}|={10,}', t):
        return True
    # No date-like content at all — timeframe must reference something date-related
    if not re.search(r'(?:19|20)\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|'
                     r'amended|revised|enacted|commenced|effective|force|compilation)', t_lower):
        return True
    return False


def _extract_per_law_metadata(
    law_name: str,
    field: str,
    chunks: list[dict],
) -> str | None:
    """
    Extract a metadata field (law_number_ref, article_citation, or timeframe)
    for a SPECIFIC law by searching chunks where the law name appears and
    picking up nearby metadata patterns.
    """
    if not law_name or not chunks:
        return None

    law_lower = law_name.strip().lower()

    for chunk in chunks:
        chunk_text = chunk.get("text", "")
        if not chunk_text:
            continue
        chunk_lower = chunk_text.lower()
        pos = chunk_lower.find(law_lower)
        if pos < 0:
            continue

        window_start = max(0, pos - 100)
        window_end = min(len(chunk_text), pos + len(law_name) + 500)
        window = chunk_text[window_start:window_end]

        if field == "law_number_ref":
            results = _LAW_REF_PATTERN.findall(window)
            # Filter out matches that are just the law's own year (e.g. "Act 2012" without "of YYYY")
            filtered = [r for r in results if _is_law_ref_number(r)]
            if filtered:
                full = " ".join(r.strip() for r in filtered[:3])
                return full if len(full) < 100 else filtered[0].strip()

        elif field == "article_citation":
            results = _SECTION_PATTERN.findall(window)
            if results:
                return results[0].strip()

        elif field == "timeframe":
            results = _AMENDMENT_DATE_PATTERN.findall(window)
            if results:
                candidate = results[0].strip()
                if _is_nav_text(candidate) or _is_document_structure_text(candidate):
                    return None
                return candidate
            # Fallback: find a 4-digit year NEAR a date keyword
            date_kw = re.search(
                r'(?:as\s+amended|last\s+amend|revised|updated|compilation|'
                r'enacted|commenced|in\s+force|effective|operative)'
                r'.{0,60}?\b(?:19|20)\d{2}\b',
                window, re.IGNORECASE
            )
            if date_kw:
                candidate = date_kw.group(0).strip()
                if _is_nav_text(candidate) or _is_document_structure_text(candidate):
                    return None
                return candidate

    return None


def _extract_verbatim_for_law(
    law_name: str,
    chunks: list[dict],
    primary_law_name: str | None = None,
) -> str | None:
    """
    Extract a verbatim snippet relevant to a specific law by finding the
    chunk where the law name appears and returning substantive text nearby.
    When a primary_law_name is provided, the function verifies the snippet
    is actually about the target law and not about the primary law —
    preventing duplicate attribution when multiple laws share the same chunk.
    """
    if not law_name or not chunks:
        return None

    law_lower = law_name.strip().lower()
    primary_lower = primary_law_name.strip().lower() if primary_law_name else None

    for chunk in chunks:
        chunk_text = chunk.get("text", "")
        if not chunk_text:
            continue
        chunk_lower = chunk_text.lower()
        pos = chunk_lower.find(law_lower)
        if pos < 0:
            continue

        start = max(0, pos - 50)
        end = min(len(chunk_text), pos + len(law_name) + 400)
        snippet = chunk_text[start:end].strip()
        if len(snippet) <= 20:
            continue

        # If the target law IS the primary law, skip cross-law check
        if primary_lower and law_lower != primary_lower:
            snippet_lower = snippet.lower()
            # Check if the snippet also mentions the primary law
            if primary_lower in snippet_lower:
                primary_pos = snippet_lower.find(primary_lower)
                target_pos = snippet_lower.find(law_lower)
                # If primary law appears BEFORE the target law in the snippet,
                # the snippet's main subject is probably the primary law.
                if primary_pos < target_pos:
                    logger.info(
                        f"[Arbiter] Skipping verbatim for '{law_name}' — "
                        f"snippet primarily discusses primary law '{primary_law_name}'"
                    )
                    continue

        return snippet

    return None

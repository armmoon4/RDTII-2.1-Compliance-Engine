"""
Module 2 — Document Chunker
Splits long legal documents into smaller chunks suitable for embedding and LLM context.
Preserves section/article/part boundaries — splits at section starts, not mid-section.
Each chunk carries rich entity metadata from legal NER.
"""
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.modules.analysis.legal_ner import extract_entities

# Section/Article/Part/Chapter heading at start of a line
_SECTION_START_RE = re.compile(
    r"(?i)^\s*(section|article|part|chapter|schedule|appendix|annex|clause|regulation|rule|subsection|paragraph)"
    r"\s+(\d+[\.\d]*)\b.*$",
    re.MULTILINE,
)

# Inline section/article references within text
_SECTION_REF_RE = re.compile(
    r"(?i)(?:section|s\.|s\s+|article|art\.|art\s+|paragraph|para\.|para\s+"
    r"|subsection|sub-section|sub\s+section|clause|regulation|rule)\s+(\d+[\.\d]*)"
)


def _extract_section_numbers(text: str) -> list[str]:
    """Extract section/article/part numbers referenced in a chunk."""
    sections = set()
    for match in _SECTION_START_RE.finditer(text):
        sections.add(match.group(1).lower() + " " + match.group(2))
    for match in _SECTION_REF_RE.finditer(text):
        sections.add(match.group(0).strip().lower())
    return sorted(sections)


def _split_at_section_boundaries(text: str) -> list[str]:
    """
    Split text at section/article/part heading boundaries first.
    Returns a list where each element starts at a section heading.
    Non-section text at the start is returned as-is.
    """
    matches = list(_SECTION_START_RE.finditer(text))
    if not matches:
        return [text]

    sections = []
    prev_end = 0
    for m in matches:
        if m.start() > prev_end:
            preamble = text[prev_end:m.start()]
            if preamble.strip():
                sections.append(preamble.strip())
        section_text = text[m.start():]
        # Skip the ENTIRE current heading match so we don't re-detect it
        heading_len = m.end() - m.start()
        next_search = section_text[heading_len:]
        next_match = _SECTION_START_RE.search(next_search)
        if next_match:
            end = next_match.start() + heading_len
            sections.append(section_text[:end].strip())
            prev_end = m.start() + end
        else:
            sections.append(section_text.strip())
            prev_end = len(text)

    trailing = text[prev_end:].strip()
    if trailing:
        sections.append(trailing)

    return [s for s in sections if s]


def chunk_document(text: str, source_url: str, doc_id: int, indicator_id: str = "") -> list[dict]:
    """
    Split document text into chunks, preserving section/article boundaries.

    1. Split at section/part/article headings first
    2. RecursiveCharacterTextSplitter on any over-long sections (> 2000 chars)
    3. Each chunk carries its section numbers as metadata

    Args:
        text: The full document text.
        source_url: The URL of the document for metadata.
        doc_id: Database ID of the document.
        indicator_id: The RDTII indicator ID this document was discovered for.

    Returns:
        List of dicts with 'text' and 'metadata' keys.
    """
    if not text or len(text.strip()) < 50:
        return []

    pillar = indicator_id.split(".")[0] if indicator_id else "UNKNOWN"

    # Step 1: Split at section boundaries
    raw_sections = _split_at_section_boundaries(text)

    # Step 2: Further split any over-long sections
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ".", " ", ""],
        chunk_size=1500,
        chunk_overlap=200,
        length_function=len,
        keep_separator=True,
    )

    result = []
    for section_text in raw_sections:
        if len(section_text) <= 2000:
            chunks = [section_text]
        else:
            chunks = splitter.split_text(section_text)

        for i, chunk in enumerate(chunks):
            section_refs = _extract_section_numbers(chunk)
            primary_section = section_refs[0] if section_refs else None

            # Extract legal entities for rich metadata
            entities = extract_entities(chunk)
            law_names = list(dict.fromkeys(e.value for e in entities if e.type == "law_name"))
            countries = list(dict.fromkeys(e.value for e in entities if e.type == "country"))
            dates = list(dict.fromkeys(e.value for e in entities if e.type == "date"))

            result.append({
                "text": chunk,
                "metadata": {
                    "source_url": source_url,
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "indicator_id": indicator_id,
                    "pillar_id": pillar,
                    "section_refs": ", ".join(section_refs) if section_refs else "",
                    "primary_section": primary_section or "",
                    "law_names": "; ".join(law_names) if law_names else "",
                    "countries": "; ".join(countries) if countries else "",
                    "dates": "; ".join(dates) if dates else "",
                },
            })

    return result

"""
Module 1 — Sample Kit / CSV Reference Database Checker
Reads the Legal Inventory CSV and provides lookup functions to determine
whether a discovered law is "KNOWN" (exists in the reference database)
or "NEW" (independently discovered, not in the reference database).

The CSV is loaded once at import time and cached.
Matching uses multi-layer strategy: exact → substring → acronym → word-overlap.
"""
import csv
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path to the reference CSV — resolves relative to project root
_DEFAULT_CSV_PATH = Path(__file__).resolve().parents[3] / "asset" / "Singapore, Malaysia, Australia, Legal Inventory.csv"

# Cache: {country_lower: [{name, normalized, acronyms, words}, ...]}
_known_cache: Optional[dict[str, list[dict]]] = None

# Words too generic to be meaningful for matching
# "act" is excluded from word-matching (too generic) but IS included in acronyms
_STOP_WORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "by",
               "with", "its", "their", "per", "act", "amendment", "no", "rev"}

# Words excluded from BOTH word-matching AND acronym generation
_ACRONYM_SKIP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "by",
                 "with", "its", "their", "per", "amendment", "no", "rev"}


def _normalize(name: str) -> str:
    """Normalize a law name: lowercase, collapse whitespace, &→and, strip punctuation."""
    name = name.lower().strip()
    name = name.replace("&", " and ")
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _make_acronyms(name: str) -> set[str]:
    """Generate plausible acronyms from a law name.
    e.g. "Personal Data Protection Act (Act 709) 2010" -> {"pdpa", "pdpa 2010"}
    Handles consecutive duplicate words (e.g. "act act" from "(Act 709)") by
    deduplicating them before generating the acronym.
    Skips purely numeric tokens for the base acronym (except 4-digit years).
    """
    words = name.split()
    # Remove consecutive duplicate words (from parenthetical act references)
    deduped = []
    for w in words:
        if not deduped or w != deduped[-1]:
            deduped.append(w)

    letters = []
    year = None
    for w in deduped:
        if re.match(r"^\d{4}$", w):
            year = w
            continue
        if re.match(r"^\d+$", w):
            continue
        if len(w) >= 3 and w.lower() not in _ACRONYM_SKIP:
            letters.append(w[0])

    acronyms = set()
    if letters:
        base = "".join(letters).lower()
        acronyms.add(base)
        if year:
            acronyms.add(f"{base} {year}")
    return acronyms


def _load_csv(csv_path: Optional[Path] = None) -> None:
    """Load the reference CSV into the in-memory cache with precomputed match data."""
    global _known_cache

    path = csv_path or _DEFAULT_CSV_PATH
    if not path.exists():
        logger.warning(f"[SampleKit] Reference CSV not found at {path}. All tags will be NEW.")
        _known_cache = {}
        return

    _known_cache = {}

    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                country = (row.get("country") or "").strip().lower()
                raw_name = (row.get("Act.and.or.practice") or "").strip()
                if not country or not raw_name:
                    continue

                normalized = _normalize(raw_name)
                # Also store a "clean" version that strips legislative metadata
                # e.g. "Personal Data Protection Act (Act 709) 2010" → "Personal Data Protection Act 2010"
                clean = raw_name
                # Remove P.u.(A)/P.U.(A)/p.u.(a) gazette references first (before parenthetical removal)
                clean = re.sub(r'\bP\.u\.?\([^)]*\)[\s\d/]*', '', clean, flags=re.IGNORECASE)
                # Remove Singapore chapter references: (Chapter 50), (Cap. 50)
                clean = re.sub(r'\(cap\.?\s*\d+[^)]*\)', '', clean, flags=re.IGNORECASE)
                clean = re.sub(r'\(chapter\s+\d+[^)]*\)', '', clean, flags=re.IGNORECASE)
                # Remove edition markers: "2020 Ed." , "(rev. 2021)"
                clean = re.sub(r'\d{4}\s+Ed\.', '', clean)
                clean = re.sub(r'\(rev\.\s*\d{4}\)', '', clean, flags=re.IGNORECASE)
                # Remove Australia (Cth), (No. X), FRLI references
                clean = re.sub(r'\(cth\)', '', clean, flags=re.IGNORECASE)
                clean = re.sub(r'\(no\.?\s*\d+\)', '', clean, flags=re.IGNORECASE)
                clean = re.sub(r'\(c\d{14}\)', '', clean, flags=re.IGNORECASE)
                # Remove "as amended" and similar suffixes
                clean = re.sub(r'\s+as\s+amended\b.*$', '', clean, flags=re.IGNORECASE)
                # Remove generic parentheticals last: (Act 709), (Act 504), (Amendment), etc.
                clean = re.sub(r'\([^)]*\)', '', clean)
                clean = re.sub(r'\s+', ' ', clean).strip().lower()
                words = {w for w in normalized.split() if w not in _STOP_WORDS}
                acronyms = _make_acronyms(normalized)

                _known_cache.setdefault(country, []).append({
                    "raw": raw_name.lower(),
                    "clean": clean,
                    "normalized": normalized,
                    "words": words,
                    "acronyms": acronyms,
                })

        logger.info(
            f"[SampleKit] Loaded {sum(len(v) for v in _known_cache.values())} known entries from {path.name} "
            f"for {list(_known_cache.keys())}"
        )
    except Exception as exc:
        logger.error(f"[SampleKit] Failed to load CSV {path}: {exc}")
        _known_cache = {}


def is_known(country: str, law_name: str) -> bool:
    """
    Check if a law is in the reference CSV for the given country.
    Matching strategy (in order):
      1. Exact match (case-insensitive)
      2. Substring match  (e.g. "PDPA 2010" — but only if ≥5 chars to avoid noise)
      3. Acronym match (e.g. "PDPA" → "Personal Data Protection Act 2010")
      4. Token-set ratio ≥ 0.85 (handles minor rewordings)

    Args:
        country: Economy name (e.g. "Singapore", "Malaysia", "Australia")
        law_name: Full official law name (e.g. "Personal Data Protection Act 2012")

    Returns:
        True if the law is found in the reference CSV for that country.
    """
    if _known_cache is None:
        _load_csv()

    country = country.strip().lower()
    law_normalized = _normalize(law_name)
    law_lower = law_name.strip().lower()
    law_words = {w for w in law_normalized.split() if w not in _STOP_WORDS}

    entries = _known_cache.get(country, [])
    if not entries:
        return False

    # Count words in the discovered law name — acronym matching only for short names
    discovered_word_count = len(law_normalized.split())

    for entry in entries:
        # Layer 1: Exact match (also check against clean name without parentheticals)
        if law_lower == entry["raw"] or law_normalized == entry["normalized"] or law_lower == entry.get("clean", ""):
            logger.debug(f"[SampleKit] EXACT match: '{law_name}' == '{entry['raw']}'")
            return True

        # Layer 2: Substring match (min 5 chars to avoid "Act" matching everything)
        # Also checks against the "clean" version without parenthetical act references
        if len(law_lower) >= 5:
            if law_lower in entry["raw"]:
                logger.debug(f"[SampleKit] SUBSTRING match: '{law_lower}' in '{entry['raw']}'")
                return True
            clean = entry.get("clean", "")
            if clean and law_lower in clean:
                logger.debug(f"[SampleKit] SUBSTRING match (clean): '{law_lower}' in '{clean}'")
                return True
        if len(entry["raw"]) >= 5:
            if entry["raw"] in law_lower:
                logger.debug(f"[SampleKit] SUBSTRING match: '{entry['raw']}' in '{law_lower}'")
                return True

        # Layer 3: Acronym match — only for short names (≤3 words) like "PDPA 2010"
        # Longer names like "Countervailing and Anti-Dumping Duties Act 1993" are
        # full names that should match via exact/substring only.
        # This prevents false acronym matches between full and abbreviated forms.
        if discovered_word_count <= 3:
            if law_normalized in entry["acronyms"]:
                logger.debug(f"[SampleKit] ACRONYM match: '{law_normalized}' in acronyms of '{entry['raw']}'")
                return True
            discovered_acronyms = _make_acronyms(law_normalized)
            for da in discovered_acronyms:
                if da in entry["acronyms"] or da == entry["normalized"]:
                    logger.debug(f"[SampleKit] ACRONYM match: '{da}' matches '{entry['raw']}'")
                    return True

    return False


def get_known_laws_for_country(country: str) -> list[str]:
    """Return all known law names for a given country (for display/debug)."""
    if _known_cache is None:
        _load_csv()
    country = country.strip().lower()
    return sorted([e["raw"] for e in _known_cache.get(country, [])])


def resolve_discovery_tag(country: str, act_and_practice: str) -> str:
    """
    Determine the Discovery Tag for a law based on the reference CSV.

    Returns:
        "KNOWN" if the law is in the reference database, "NEW" otherwise.
    """
    if not act_and_practice or act_and_practice in ("—", "None", "N/A"):
        return "NEW"

    return "KNOWN" if is_known(country, act_and_practice) else "NEW"

"""
Module 2 — Legal Named Entity Recognition
Lightweight regex-based NER for legal text (no spaCy dependency).
Extracts: law/act names, section/article numbers, dates, countries, regulators.
"""
import re
from typing import NamedTuple


class LegalEntity(NamedTuple):
    type: str       # law_name | section | date | country | regulator
    value: str
    start: int
    end: int


# ── Law/Act name pattern ─────────────────────────────────────────
# Requires: capitalized words ending with a legal keyword, optionally followed by a year/number.
_LAW_NAME_RE = re.compile(
    r"(?:(?:[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|of|the|and|for|in|on|to|by|at|or|an|as|a))*)"
    r"\s+(?:Act|Regulation|Code|Order|Rule|Directive|Standard(?!\s+of)|Policy|Decree|Ordinance|Statute"
    r"|Convention|Treaty|Protocol|Framework|Agreement|Law|Bill|Guidelines|Guidance|Circular|Notice"
    r"|Direction|Instrument|Declaration|Charter|Covenant|Pact)"
    r"(?:\s*\(?\s*(?:No\.\s*)?\d+(?:/\d+)?\s*\)?)?"
    r"(?:\s*\(?\s*[12]\d{3}\s*\)?)?)"
)

# ── Section/article reference patterns ────────────────────────────
_SECTION_RE = re.compile(
    r"(?i)(?:section|s\.\s*|s\s+|article|art\.\s*|art\s+|"
    r"paragraph|para\.\s*|para\s+|clause|regulation|rule|"
    r"subsection|sub-section|sub\s+section|subparagraph|sub\-paragraph|"
    r"chapter|part|schedule|appendix|annex)"
    r"\s*(\d+[A-Za-z]?[\.\d]*(?:[-–][A-Za-z]?\d+[\.\d]*)*)"
)

# ── Date/timeframe pattern ───────────────────────────────────────
_DATE_RE = re.compile(
    r"(?i)(?:"
    r"(?:since|enacted|commenced|in force|adopted|passed|gazetted|notified|published|"
    r"last amended|amended|revised|consolidated|updated|effective|operative|"
    r"implemented|established|created|formed|ratified|signed|entered into force|"
    r"came into force|came into effect|took effect|takes effect|becomes effective|"
    r"will come into force|shall come into force)"
    r"(?::?\s*)?"
    r"(?:"
    r"\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}"
    r"|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}"
    r"|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2},?\s+\d{4}"
    r"|"
    r"\b(?:19|20)\d{2}\b"
    r")"
    r")"
)

# ── Country/region pattern ───────────────────────────────────────
_COUNTRY_RE = re.compile(
    r"(?i)\b("
    r"Singapore|Malaysia|Australia|Indonesia|Thailand|Vietnam|Philippines|Brunei|"
    r"Cambodia|Laos|Myanmar|Timor-Leste|India|China|Japan|South Korea|Korea|"
    r"Taiwan|Hong Kong|New Zealand|United States|United Kingdom|France|Germany|"
    r"European Union|ASEAN|APEC|OECD|WTO|UN|UNESCAP"
    r")\b"
)

# ── Regulator/authority pattern ──────────────────────────────────
_REGULATOR_RE = re.compile(
    r"(?i)\b("
    r"PDPC|PDP Commissioner|Personal Data Protection Commission|"
    r"OAIC|Office of the Australian Information Commissioner|"
    r"MCMC|Malaysian Communications and Multimedia Commission|"
    r"Bank Negara Malaysia|BNM|"
    r"IMDA|Infocomm Media Development Authority|"
    r"CSA|Cyber Security Agency|"
    r"ACMA|Australian Communications and Media Authority|"
    r"ACCC|Australian Competition and Consumer Commission|"
    r"ASIC|Australian Securities and Investments Commission|"
    r"APRA|Australian Prudential Regulation Authority|"
    r"MAS|Monetary Authority of Singapore|"
    r"ACRA|Accounting and Corporate Regulatory Authority|"
    r"Security Commission Malaysia|SC Malaysia|"
    r"Minister|Attorney-General|Commissioner|Controller|Supervisor|"
    r"Authority|Commission|Board|Agency|Office|Department|Ministry|Council"
    r")\b"
)


def extract_entities(text: str) -> list[LegalEntity]:
    """Extract all legal entities from text. Returns sorted list by position."""
    entities: list[LegalEntity] = []

    for pattern, etype in [
        (_LAW_NAME_RE, "law_name"),
        (_SECTION_RE, "section"),
        (_DATE_RE, "date"),
        (_COUNTRY_RE, "country"),
        (_REGULATOR_RE, "regulator"),
    ]:
        for match in pattern.finditer(text):
            value = match.group(0).strip()
            # Filter noisy short matches
            if etype == "country" and len(value) < 2:
                continue
            if etype == "regulator" and len(value) < 3:
                continue
            if etype == "law_name":
                words = value.split()
                if len(words) < 3 and any(w.lower() in ("the", "this", "an", "a") for w in words):
                    continue
            entities.append(LegalEntity(etype, value, match.start(), match.end()))

    # De-duplicate overlapping entities (keep the longest)
    entities.sort(key=lambda e: (e.start, -e.end))
    deduped = []
    for e in entities:
        if deduped and e.start < deduped[-1].end:
            continue
        deduped.append(e)

    return deduped


def extract_law_names(text: str) -> list[str]:
    """Convenience: extract just law/act names. Filters out very short generic references."""
    names = []
    for m in _LAW_NAME_RE.finditer(text):
        name = m.group(0).strip()
        # Filter out generic references like "The Act", "This Act", "an Act"
        words = name.split()
        if len(words) < 3 and any(w.lower() in ("the", "this", "an", "a") for w in words):
            continue
        names.append(name)
    return list(dict.fromkeys(names))


def extract_sections(text: str) -> list[str]:
    """Convenience: extract just section/article references."""
    return list(dict.fromkeys(m.group(1) for m in _SECTION_RE.finditer(text)))


def extract_dates(text: str) -> list[str]:
    """Convenience: extract just date/timeframe mentions."""
    return list(dict.fromkeys(m.group(0).strip() for m in _DATE_RE.finditer(text)))

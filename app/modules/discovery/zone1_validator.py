"""
Module 1 — Zone 1 Validator
Enforces Zone 1 legal hierarchy checks from RDTII spec §3.1.4:
- Formal adoption check (exclude drafts)
- Effective date check (exclude future-dated)
- Current status check (exclude repealed)
"""
import logging
import re
from datetime import datetime, timezone

from app.models.discovered_document import EnforcementStatus

logger = logging.getLogger(__name__)

# Heuristic patterns for validation
REPEAL_PATTERNS = [
    r"repealed by", r"revoked by", r"no longer in force", 
    r"superseded by", r"replaced by"
]

DRAFT_PATTERNS = [
    r"this is a draft", r"draft for consultation", r"exposure draft",
    r"proposed bill", r"consultation paper"
]

FUTURE_DATE_PATTERNS = [
    r"enters into force on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    r"effective from\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    r"commencement date\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
]

def _parse_date(date_str: str) -> datetime | None:
    """Attempt to parse a date string into a datetime object."""
    from dateutil import parser
    try:
        # fuzzy=True allows it to ignore surrounding text
        return parser.parse(date_str, fuzzy=True)
    except Exception:
        return None

def validate_enforcement_status(text: str) -> EnforcementStatus:
    """
    Analyse document text to determine if it's currently in force.
    Applies heuristics to check for drafts, repeals, and future effective dates.
    """
    if not text:
        return EnforcementStatus.UNKNOWN
        
    text_lower = text.lower()
    
    # 1. Draft check (usually at the top of the document)
    top_text = text_lower[:5000]
    if any(re.search(pat, top_text) for pat in DRAFT_PATTERNS):
        return EnforcementStatus.DRAFT
        
    # 2. Repeal check
    if any(re.search(pat, top_text) for pat in REPEAL_PATTERNS):
        return EnforcementStatus.REPEALED
        
    # 3. Future date check
    for pat in FUTURE_DATE_PATTERNS:
        match = re.search(pat, top_text)
        if match:
            date_str = match.group(1)
            effective_date = _parse_date(date_str)
            if effective_date:
                now = datetime.now(tz=timezone.utc)
                aware_date = effective_date.replace(tzinfo=timezone.utc) if effective_date.tzinfo is None else effective_date
                if aware_date > now:
                    logger.info(f"[Zone1] Document is future-dated: {aware_date.date()}")
                    return EnforcementStatus.FUTURE_DATED
                
    # If no red flags found, assume it's in force
    return EnforcementStatus.IN_FORCE

def run_zone1_validation(text: str) -> tuple[bool, EnforcementStatus]:
    """
    Run full Zone 1 validation.
    Returns:
        (zone1_passed: bool, status: EnforcementStatus)
    """
    status = validate_enforcement_status(text)
    passed = status in (EnforcementStatus.IN_FORCE, EnforcementStatus.UNKNOWN)
    
    if not passed:
        logger.warning(f"[Zone1] Validation failed. Status: {status.name}")
        
    return passed, status

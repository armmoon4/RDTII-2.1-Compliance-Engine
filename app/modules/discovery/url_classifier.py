"""
Module 1 — URL Classifier
Implements Zone 1 URL routing from RDTII spec §6.5.6.
Classifies each discovered URL as PRIMARY, SECONDARY, or EXCLUDED.
"""
import re
import logging
from urllib.parse import urlparse

from app.models.discovered_document import SourceType
from app.modules.discovery.query_generator import COUNTRY_PORTAL_REGISTRY

logger = logging.getLogger(__name__)

# Patterns that indicate a draft/non-enforced document
DRAFT_URL_PATTERNS = [
    r"draft", r"consultation", r"proposed", r"discussion-paper",
    r"exposure-draft", r"bill-\d+", r"green-paper",
]

# Patterns for international DB fallback sources
UNCTAD_DOMAINS = ["unctad.org", "trains.unctad.org"]
WORLD_BANK_DOMAINS = ["worldbank.org", "openknowledge.worldbank.org"]

# Indicators where approved secondary sources (UNCTAD/WB) may be scored
APPROVED_SECONDARY_INDICATORS = {"3.4", "5.3", "9.1"}

# Domains that are always secondary leads only
SECONDARY_LEAD_DOMAINS = [
    "wikipedia.org", "lexology.com", "mondaq.com", "bakermckenzie.com",
    "cliffordchance.com", "reuters.com", "bloomberg.com", "nytimes.com",
    "theguardian.com", "academica.edu", "ssrn.com", "scholar.google.com",
]

# Domains to exclude entirely (social media, video, non-regulatory)
EXCLUDED_DOMAINS = [
    "youtube.com", "youtu.be", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "linkedin.com", "tiktok.com", "reddit.com",
    "pinterest.com", "snapchat.com", "tumblr.com",
]


def _extract_domain(url: str) -> str:
    """Extract the registered domain from a URL."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _is_gov_domain(domain: str) -> bool:
    """Check if domain is a government domain."""
    gov_tlds = [".gov.my", ".gov.sg", ".gov.au", ".gov.bd", ".go.id", ".gov"]
    return any(domain.endswith(tld) for tld in gov_tlds)


def _matches_known_portal(domain: str, country: str) -> tuple[bool, bool]:
    """
    Check if domain matches the country's known primary portals.

    Returns:
        (is_legislation_portal, is_gazette_portal)
    """
    portal_meta = COUNTRY_PORTAL_REGISTRY.get(country)
    if not portal_meta:
        return False, False

    is_legislation = portal_meta.legislation_portal in domain
    is_gazette = portal_meta.gazette_portal in domain
    is_regulator = portal_meta.ict_regulator_portal in domain

    return (is_legislation or is_regulator), is_gazette


def _has_draft_pattern(url: str) -> bool:
    """Return True if URL path suggests a draft/consultation document."""
    url_lower = url.lower()
    return any(re.search(pat, url_lower) for pat in DRAFT_URL_PATTERNS)


def classify_url(url: str, country: str, indicator_id: str = "") -> SourceType:
    """
    Classify a URL according to RDTII Zone 1 routing rules.

    Args:
        url: The discovered URL to classify.
        country: Target country (Malaysia, Singapore, Australia).
        indicator_id: RDTII indicator ID — affects SECONDARY_APPROVED logic.

    Returns:
        SourceType enum value.
    """
    country = country.strip().title()
    domain = _extract_domain(url)

    # Check for excluded domains (social media, video)
    if any(exc in domain for exc in EXCLUDED_DOMAINS):
        logger.debug(f"[Classify] EXCLUDED (social/video domain): {domain}")
        return SourceType.EXCLUDED

    # Check for draft patterns in URL
    if _has_draft_pattern(url):
        logger.debug(f"[Classify] EXCLUDED (draft URL pattern): {url}")
        return SourceType.EXCLUDED

    # Check secondary lead domains first (highest certainty of being non-primary)
    if any(sec in domain for sec in SECONDARY_LEAD_DOMAINS):
        logger.debug(f"[Classify] SECONDARY_LEAD (known secondary domain): {domain}")
        return SourceType.SECONDARY_LEAD

    # UNCTAD / World Bank
    if any(ub in domain for ub in UNCTAD_DOMAINS + WORLD_BANK_DOMAINS):
        if indicator_id in APPROVED_SECONDARY_INDICATORS:
            logger.debug(f"[Classify] SECONDARY_APPROVED for {indicator_id}: {domain}")
            return SourceType.SECONDARY_APPROVED
        return SourceType.SECONDARY_LEAD

    # Known primary portals (highest confidence)
    is_legislation, is_gazette = _matches_known_portal(domain, country)
    if is_legislation:
        logger.debug(f"[Classify] PRIMARY_HIGH (known portal): {domain}")
        return SourceType.PRIMARY_HIGH
    if is_gazette:
        logger.debug(f"[Classify] PRIMARY_GAZETTE (gazette portal): {domain}")
        return SourceType.PRIMARY_GAZETTE

    # Any .gov domain (medium confidence)
    if _is_gov_domain(domain):
        logger.debug(f"[Classify] PRIMARY_MEDIUM (gov domain): {domain}")
        return SourceType.PRIMARY_MEDIUM

    # Default: secondary lead
    logger.debug(f"[Classify] SECONDARY_LEAD (default): {domain}")
    return SourceType.SECONDARY_LEAD


def extract_law_references(snippet: str) -> list[str]:
    """
    Extract probable law names from a secondary source snippet.
    These are queued as follow-up searches.

    Heuristics: capitalised Act/Law/Code/Regulation patterns.
    """
    pattern = r"[A-Z][A-Za-z\s]+(?:Act|Law|Code|Regulation|Ordinance|Order|Decree)\s*\d{0,4}"
    matches = re.findall(pattern, snippet)
    return list(set(m.strip() for m in matches if len(m.strip()) > 5))

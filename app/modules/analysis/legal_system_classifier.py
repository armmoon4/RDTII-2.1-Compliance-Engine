"""
Module 2 — Legal System Classifier
Classifies economy legal system based on RDTII Zone 1 source identification.
Sets flag to determine if case law is permitted as a primary source.
"""
import logging
from typing import Literal

logger = logging.getLogger(__name__)

LegalSystem = Literal["civil", "common", "mixed"]

# Hardcoded registry for the target hackathon economies
# According to spec §3.1.1
KNOWN_LEGAL_SYSTEMS: dict[str, LegalSystem] = {
    "Malaysia": "common",
    "Singapore": "common",
    "Australia": "common",
    "Bangladesh": "mixed",
    "India": "common",
    "Philippines": "mixed",
    "Myanmar": "mixed",
    "China": "civil", # Note: case law DOES NOT count
}

def classify_legal_system(country: str) -> LegalSystem:
    """
    Classifies the legal system for a given country.
    Defaults to civil if unknown.
    """
    country_title = country.strip().title()
    system = KNOWN_LEGAL_SYSTEMS.get(country_title)
    
    if system:
        logger.info(f"[Legal System] {country_title} classified as '{system}'.")
        return system
        
    logger.warning(f"[Legal System] Unknown country '{country_title}', defaulting to 'civil'.")
    return "civil"

def is_case_law_permitted(system: LegalSystem) -> bool:
    """Returns True if case law can be considered a binding primary source."""
    return system == "common"

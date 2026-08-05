"""
Module 1 — Language Processor
Detects language and machine-translates non-English documents to English.
Uses langdetect and deep-translator (Google Translate backend).
"""
import logging
from typing import Optional

from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory

# Set seed for deterministic language detection
DetectorFactory.seed = 0

logger = logging.getLogger(__name__)


def detect_language(text: str) -> str:
    """Detect language code of the given text (e.g., 'en', 'ms', 'bn')."""
    if not text or len(text.strip()) < 10:
        return "en"
    try:
        # Detect based on first 2000 chars for speed
        lang = detect(text[:2000])
        return lang
    except Exception as e:
        logger.warning(f"[Language] Detection failed, defaulting to 'en': {e}")
        return "en"


def translate_to_english(text: str) -> Optional[str]:
    """
    Translate text to English using deep-translator (Google Translate).
    Chunks text into 4000-character blocks to respect API limits.
    """
    if not text:
        return None

    logger.info(f"[Language] Translating {len(text)} characters to English...")
    translator = GoogleTranslator(source="auto", target="en")

    # Chunk size safely below Google Translate's ~5000 char limit
    chunk_size = 4000
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    
    translated_chunks = []
    try:
        for i, chunk in enumerate(chunks):
            res = translator.translate(chunk)
            if res:
                translated_chunks.append(res)
        
        translated_text = "\n".join(translated_chunks)
        logger.info(f"[Language] Translation complete.")
        return translated_text
    except Exception as e:
        logger.error(f"[Language] Translation failed: {e}")
        return None


def process_document_language(text: str) -> tuple[str, str, Optional[str]]:
    """
    Process document text:
    1. Detect language
    2. If not English, translate
    
    Returns:
        (language_code, original_text, translated_text_or_none)
    """
    lang = detect_language(text)
    
    if lang == "en":
        return "en", text, None
        
    translated = translate_to_english(text)
    return lang, text, translated

"""
Module 1 — Document Downloader
Downloads HTML pages and PDFs from primary sources.
Uses Playwright for JS-rendered pages and httpx for static content.
Extracts text from PDFs using pdfplumber → PyMuPDF → pdfminer.six → pypdf.
Falls back to Tesseract OCR for scanned/image-only PDFs.
"""
import asyncio
import hashlib
import logging
import os
import re
import ssl
import tempfile
from io import BytesIO
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CONTENT_BYTES = 50 * 1024 * 1024  # 50 MB
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_DEFAULT_SSL_CONTEXT = ssl.create_default_context()


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


PDF_MAGIC = b"%PDF"


def _is_pdf_content(raw_bytes: bytes) -> bool:
    """Detect PDF by magic bytes — works even when content-type or extension is wrong."""
    return raw_bytes[:4] == PDF_MAGIC


def _extract_pdf_text(raw_bytes: bytes) -> tuple[str, float]:
    """
    Extract text from PDF bytes using multi-engine pipeline:
    1. pdfplumber (best layout preservation)
    2. PyMuPDF (fast extraction)
    3. pdfminer.six (fallback)
    4. pypdf (last-resort digital extraction)
    5. Tesseract OCR (scanned/image-only PDFs)

    Returns:
        Tuple of (extracted_text, ocr_quality_cer)
        ocr_quality_cer = Character Error Rate estimate (0.0 = perfect, 1.0 = unusable)
    """
    if not _is_pdf_content(raw_bytes):
        return "", 0.0

    # 1. pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
            if len(pdf.pages) > 500:
                logger.warning(f"[Download] pdfplumber: {len(pdf.pages)} pages — too large")
                return "", 0.0
            pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(pages).strip()
        if text and len(text) > 100:
            return text, 0.0
    except Exception:
        pass

    # 2. PyMuPDF
    try:
        import fitz
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        pages = [page.get_text() or "" for page in doc]
        text = "\n".join(pages).strip()
        doc.close()
        if text and len(text) > 100:
            return text, 0.0
    except Exception:
        pass

    # 3. pdfminer.six
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(BytesIO(raw_bytes))
        if text and len(text.strip()) > 100:
            return text.strip(), 0.0
    except Exception:
        pass

    # 4. pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(BytesIO(raw_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if text and len(text) > 50:
            return text, 0.02
    except Exception:
        pass

    # 5. Tesseract OCR — scanned/image-only PDF fallback
    try:
        from pdf2image import convert_from_bytes
        import pytesseract

        logger.info("[Download] Digital extraction empty — trying OCR for scanned PDF...")
        images = convert_from_bytes(raw_bytes, dpi=300)
        ocr_pages = []
        total_chars = 0
        error_chars = 0
        for img in images:
            page_text = pytesseract.image_to_string(img, lang="eng")
            ocr_pages.append(page_text)
            total_chars += len(page_text)
        text = "\n".join(ocr_pages).strip()
        if text and len(text) > 50:
            cer = 0.15  # conservative CER estimate for Tesseract
            logger.info(f"[Download] OCR extracted {len(text)} chars across {len(images)} pages")
            return text, cer
    except ImportError:
        logger.warning("[Download] pytesseract/pdf2image not installed — cannot OCR scanned PDFs")
    except Exception as e:
        logger.warning(f"[Download] OCR failed: {e}")

    return "", 0.0


def _extract_html_text(html: str, url: str) -> str:
    """Extract main text content from HTML using BeautifulSoup."""
    try:
        soup = BeautifulSoup(html, "lxml")
        # Remove script/style/nav/footer noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception as e:
        logger.warning(f"[Download] HTML parsing failed for {url}: {e}")
        return html[:50000]  # raw truncated fallback


async def _try_httpx(url: str) -> tuple[Optional[str], Optional[str], float]:
    """Attempt to download a URL using httpx with proper SSL context."""
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        verify=_DEFAULT_SSL_CONTEXT,
    ) as client:
        response = await client.get(url)
        content_type = response.headers.get("content-type", "").lower()
        raw_bytes = response.content

        if len(raw_bytes) > MAX_CONTENT_BYTES:
            return None, f"Document too large: {len(raw_bytes)} bytes", 0.0

        # Check for rate limiting
        if response.status_code == 429:
            retry_after = int(response.headers.get("retry-after", "5"))
            raise ValueError(f"Rate limited (429), retry after {retry_after}s")

        response.raise_for_status()

        is_pdf = _is_pdf_content(raw_bytes) or "pdf" in content_type or url.lower().endswith(".pdf")
        if is_pdf:
            text, cer = _extract_pdf_text(raw_bytes)
            if text:
                logger.info(f"[Download] PDF downloaded: {url[:80]} ({len(text)} chars, cer={cer})")
                return text, None, cer
            return None, "PDF text extraction returned empty", cer
        else:
            text = _extract_html_text(response.text, url)
            if text and len(text) > 200:
                logger.info(f"[Download] HTML downloaded: {url[:80]} ({len(text)} chars)")
                return text, None, 0.0
            raise ValueError("Content too short")


async def _try_playwright(url: str) -> tuple[Optional[str], Optional[str], float]:
    """Fallback: download using Playwright for JS-rendered pages."""
    from playwright.async_api import async_playwright
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            page = await browser.new_page(extra_http_headers=HEADERS)
            await page.goto(url, timeout=TIMEOUT_SECONDS * 1000, wait_until="networkidle")
            html = await page.content()
            text = _extract_html_text(html, url)
            if text and len(text) > 200:
                logger.info(f"[Download] Playwright downloaded: {url[:80]} ({len(text)} chars)")
                return text, None, 0.0
            return None, "Playwright returned empty content", 0.0
    finally:
        if browser is not None:
            await browser.close()


async def download_document(url: str) -> tuple[Optional[str], Optional[str], float]:
    """
    Download a document from a URL. Returns (content_text, error_message, ocr_quality).

    Tries httpx first with retries and exponential backoff; falls back to Playwright
    for JS-rendered pages.

    Returns:
        Tuple of (extracted_text or None, error_message or None, ocr_quality_cer)
        ocr_quality_cer = 0.0 for digital extraction, >0.0 for OCR (scanned PDFs)
    """
    # ── httpx attempt with retries ───────────────────────────────────────────
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            text, error, cer = await _try_httpx(url)
            return text, error, cer
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "response", None) and getattr(exc.response, "status_code", None)
            if status_code == 429:
                retry_after = int(getattr(getattr(exc, "response", None), "headers", {}).get("retry-after", "5"))
                logger.info(f"[Download] Rate limited on {url[:60]}... retrying in {retry_after}s (attempt {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(retry_after)
            elif attempt < MAX_RETRIES - 1:
                delay = 1.5 ** attempt
                logger.debug(f"[Download] httpx attempt {attempt+1} failed for {url[:60]}... retrying in {delay}s: {exc}")
                await asyncio.sleep(delay)
            else:
                logger.debug(f"[Download] httpx failed for {url}: {exc}. Trying Playwright...")

    # ── Playwright fallback ──────────────────────────────────────────────────
    try:
        return await _try_playwright(url)
    except Exception as pw_err:
        error = f"httpx ({last_error}) and Playwright ({pw_err}) both failed"
        logger.warning(f"[Download] FAILED for {url}: {error}")
        return None, error, 0.0


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of text content for deduplication."""
    return _compute_hash(text)

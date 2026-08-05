"""
Unit tests for Module 1 — Document Discovery (crawler, downloader, classifiers).
Uses mocked HTTP responses to avoid live network calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Query Generator Tests ────────────────────────────────────────────────────

class TestQueryGenerator:
    """Tests for app.modules.discovery.query_generator"""

    def test_generate_queries_malaysia_6_1(self):
        from app.modules.discovery.query_generator import generate_queries
        from app.config import settings
        queries = generate_queries("Malaysia", "6.1")
        assert len(queries) >= 5
        # Queries must be sorted by priority
        priorities = [q.priority for q in queries]
        assert priorities == sorted(priorities)
        # All text queries must contain the country name. Skip:
        #   - llm_enhanced queries (LLM may or may not include country)
        #   - portal_direct queries (these are URLs, not search strings)
        for q in queries:
            if q.strategy.startswith("llm_enhanced") or q.strategy == "portal_direct":
                continue
            assert "Malaysia" in q.query_string, f"Strategy={q.strategy}: {q.query_string[:100]}"

    def test_generate_queries_singapore_7_4(self):
        from app.modules.discovery.query_generator import generate_queries
        queries = generate_queries("Singapore", "7.4")
        # Must include DPO/DPIA keyword seeds
        combined = " ".join(q.query_string for q in queries)
        assert "DPO" in combined or "data protection officer" in combined.lower()

    def test_generate_queries_unknown_indicator_raises(self):
        from app.modules.discovery.query_generator import generate_queries
        with pytest.raises(ValueError, match="Unknown indicator_id"):
            generate_queries("Malaysia", "99.99")

    def test_generate_queries_unsupported_country_raises(self):
        from app.modules.discovery.query_generator import generate_queries
        with pytest.raises(ValueError, match="Unsupported country"):
            generate_queries("Wakanda", "6.1")

    def test_all_61_indicators_covered(self):
        from app.modules.discovery.query_generator import INDICATOR_QUESTION_BANK
        expected_ids = [
            "1.4", "2.1", "2.2", "2.3",
            "3.1", "3.2", "3.3", "3.4", "3.5",
            "4.01", "4.2", "4.3", "4.5", "4.6", "4.9", "4.10",
            "5.1", "5.2", "5.3", "5.4", "5.5", "5.7",
            "6.1", "6.2", "6.3", "6.4",
            "7.1", "7.2", "7.3", "7.4", "7.5",
            "8.1", "8.2", "8.3", "8.4",
            "9.1", "9.3", "9.4",
            "10.1", "10.2", "10.3", "10.4",
            "11.1", "11.2", "11.3", "11.4",
            "12.01", "12.2", "12.3", "12.4.1", "12.4.2",
            "12.4.3", "12.4.4", "12.4.5", "12.4.6", "12.4.7",
            "12.5", "12.6", "12.7", "12.8", "12.9",
        ]
        for ind_id in expected_ids:
            assert ind_id in INDICATOR_QUESTION_BANK, f"Missing indicator: {ind_id}"

    def test_query_strategies_present(self):
        from app.modules.discovery.query_generator import generate_queries
        queries = generate_queries("Australia", "7.1")
        strategies = {q.strategy for q in queries}
        # Must have portal-targeted and fallback strategies
        assert "portal_targeted" in strategies
        assert "keyword_fallback" in strategies


# ─── URL Classifier Tests ─────────────────────────────────────────────────────

class TestUrlClassifier:
    """Tests for app.modules.discovery.url_classifier"""

    def test_known_portal_malaysia(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://agc.gov.my/akta/vol. 1/act 709 bi.pdf", "Malaysia", "6.1")
        assert result == SourceType.PRIMARY_HIGH

    def test_gazette_portal_malaysia(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://federalgazette.agc.gov.my/outputp/pua_20240101.pdf", "Malaysia", "7.1")
        assert result == SourceType.PRIMARY_GAZETTE

    def test_gov_domain_medium(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://mcmc.gov.my/en/regulations", "Malaysia", "5.5")
        assert result == SourceType.PRIMARY_MEDIUM

    def test_wikipedia_is_secondary_lead(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://en.wikipedia.org/wiki/Personal_data_protection", "Malaysia", "7.1")
        assert result == SourceType.SECONDARY_LEAD

    def test_draft_url_excluded(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://agc.gov.my/draft-data-protection-bill-2024", "Malaysia", "7.1")
        assert result == SourceType.EXCLUDED

    def test_unctad_approved_secondary(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://unctad.org/trains/report", "Malaysia", "5.3")
        assert result == SourceType.SECONDARY_APPROVED

    def test_unctad_non_approved_indicator(self):
        from app.modules.discovery.url_classifier import classify_url
        from app.models.discovered_document import SourceType
        result = classify_url("https://unctad.org/trains/report", "Malaysia", "6.1")
        assert result == SourceType.SECONDARY_LEAD


# ─── Zone 1 Validator Tests ───────────────────────────────────────────────────

class TestZone1Validator:
    """Tests for app.modules.discovery.zone1_validator"""

    def test_in_force_document(self):
        from app.modules.discovery.zone1_validator import run_zone1_validation
        from app.models.discovered_document import EnforcementStatus
        text = "This Act may be cited as the Personal Data Protection Act 2010."
        passed, status = run_zone1_validation(text)
        assert passed is True
        assert status == EnforcementStatus.IN_FORCE

    def test_draft_document_fails(self):
        from app.modules.discovery.zone1_validator import run_zone1_validation
        from app.models.discovered_document import EnforcementStatus
        text = "This is a draft for consultation. This document is not yet law."
        passed, status = run_zone1_validation(text)
        assert passed is False
        assert status == EnforcementStatus.DRAFT

    def test_repealed_document_fails(self):
        from app.modules.discovery.zone1_validator import run_zone1_validation
        from app.models.discovered_document import EnforcementStatus
        text = "This regulation was repealed by the Data Protection Act 2022."
        passed, status = run_zone1_validation(text)
        assert passed is False
        assert status == EnforcementStatus.REPEALED

    def test_empty_text_returns_unknown(self):
        from app.modules.discovery.zone1_validator import run_zone1_validation
        from app.models.discovered_document import EnforcementStatus
        passed, status = run_zone1_validation("")
        assert status == EnforcementStatus.UNKNOWN


# ─── Document Downloader Tests ────────────────────────────────────────────────

class TestDocumentDownloader:
    """Tests for app.modules.discovery.document_downloader (mocked HTTP)"""

    @pytest.mark.asyncio
    async def test_html_download_success(self):
        from app.modules.discovery.document_downloader import download_document

        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.content = b"<html><body><p>" + b"x" * 500 + b"</p></body></html>"
        mock_response.text = "<html><body><p>" + "x" * 500 + "</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.get = AsyncMock(return_value=mock_response)
            text, error, ocr_cer = await download_document("https://agc.gov.my/test.html")
            assert text is not None
            assert len(text) >= 500
            assert error is None
            assert ocr_cer is None or ocr_cer == 0.0

    @pytest.mark.asyncio
    async def test_download_failure_returns_none(self):
        from app.modules.discovery.document_downloader import download_document

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
            with patch("playwright.async_api.async_playwright") as mock_pw:
                mock_pw.return_value.__aenter__ = AsyncMock(side_effect=Exception("Playwright unavailable"))
                text, error, ocr_cer = await download_document("https://unreachable.example.com/doc.pdf")
                assert text is None
                assert error is not None

    def test_compute_content_hash_is_sha256(self):
        from app.modules.discovery.document_downloader import compute_content_hash
        import hashlib
        sample = "Test document content"
        expected = hashlib.sha256(sample.encode("utf-8")).hexdigest()
        assert compute_content_hash(sample) == expected
        assert len(compute_content_hash(sample)) == 64  # SHA-256 = 64 hex chars


# ─── Language Processor Tests ─────────────────────────────────────────────────

class TestLanguageProcessor:
    """Tests for app.modules.discovery.language_processor"""

    def test_english_detection(self):
        from app.modules.discovery.language_processor import detect_language
        lang = detect_language("This is an English legal document about data protection.")
        assert lang == "en"

    def test_process_english_no_translation(self):
        from app.modules.discovery.language_processor import process_document_language
        text = "This is an English legal document about data protection."
        lang, orig, translated = process_document_language(text)
        assert lang == "en"
        assert orig == text
        assert translated is None

    def test_empty_text_returns_english(self):
        from app.modules.discovery.language_processor import detect_language
        lang = detect_language("")
        assert lang == "en"

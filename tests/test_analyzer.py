"""
Unit tests for Module 2 — Analysis Engine (AI client, scorer, agents, orchestrator).
Uses fixture JSON to avoid live LLM API calls.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


# ─── Scoring Engine Tests ─────────────────────────────────────────────────────

class TestScoringEngine:
    """Tests for app.modules.analysis.scoring_engine"""

    def test_validate_exact_score(self):
        from app.modules.analysis.scoring_engine import validate_score
        assert validate_score("6.1", 1.0) == 1.0
        assert validate_score("6.1", 0.5) == 0.5
        assert validate_score("6.1", 0.0) == 0.0

    def test_validate_score_snaps_to_nearest(self):
        from app.modules.analysis.scoring_engine import validate_score
        # 0.4 snaps to 0.5 (nearest valid for 6.1 which has [1.0, 0.5, 0.0])
        result = validate_score("6.1", 0.4)
        assert result == 0.5

    def test_validate_score_binary_indicator(self):
        from app.modules.analysis.scoring_engine import validate_score
        # 7.3 only has [1.0, 0.0]
        assert validate_score("7.3", 0.8) == 1.0
        assert validate_score("7.3", 0.2) == 0.0

    def test_validate_score_unknown_indicator_raises(self):
        from app.modules.analysis.scoring_engine import validate_score
        with pytest.raises(ValueError, match="Unknown indicator ID"):
            validate_score("99.99", 0.5)

    def test_get_indicator_ids_for_all_pillars(self):
        from app.modules.analysis.scoring_engine import get_indicator_ids_for_pillars
        all_ids = get_indicator_ids_for_pillars(None)
        assert len(all_ids) > 40  # All 61 indicators
        assert "6.1" in all_ids
        assert "12.9" in all_ids

    def test_get_indicator_ids_for_pillar_6(self):
        from app.modules.analysis.scoring_engine import get_indicator_ids_for_pillars
        pillar6_ids = get_indicator_ids_for_pillars([6])
        assert "6.1" in pillar6_ids
        assert "6.2" in pillar6_ids
        assert "6.3" in pillar6_ids
        assert "6.4" in pillar6_ids
        assert "7.1" not in pillar6_ids

    def test_get_indicator_ids_for_pillar_7(self):
        from app.modules.analysis.scoring_engine import get_indicator_ids_for_pillars
        pillar7_ids = get_indicator_ids_for_pillars([7])
        assert "7.1" in pillar7_ids
        assert "7.5" in pillar7_ids
        assert "6.1" not in pillar7_ids

    def test_all_valid_scores_non_empty(self):
        from app.modules.analysis.scoring_engine import VALID_SCORES
        for ind_id, scores in VALID_SCORES.items():
            assert len(scores) >= 2, f"Indicator {ind_id} has fewer than 2 valid scores"
            assert 0.0 in scores, f"Indicator {ind_id} missing 0.0 score"


# ─── Indicator Mapper Tests ────────────────────────────────────────────────────

class TestIndicatorMapper:
    """Tests for app.modules.analysis.indicator_mapper"""

    def test_cybersecurity_warning_for_6_1(self):
        from app.modules.analysis.indicator_mapper import map_semantic_context
        text = "All operators must comply with cybersecurity standards and security requirements."
        ctx = map_semantic_context(text, "6.1")
        assert ctx["semantic_warning"] is not None
        assert "cybersecurity" in ctx["semantic_warning"].lower()

    def test_government_data_warning_for_6_2(self):
        from app.modules.analysis.indicator_mapper import map_semantic_context
        text = "Government data and public sector records must be stored domestically."
        ctx = map_semantic_context(text, "6.2")
        assert ctx["semantic_warning"] is not None

    def test_maximum_retention_warning_for_7_3(self):
        from app.modules.analysis.indicator_mapper import map_semantic_context
        text = "Data must not be kept for longer than necessary for its purpose."
        ctx = map_semantic_context(text, "7.3")
        assert ctx["semantic_warning"] is not None

    def test_no_warning_for_irrelevant_text(self):
        from app.modules.analysis.indicator_mapper import map_semantic_context
        text = "Companies shall appoint a Data Protection Officer within 30 days."
        ctx = map_semantic_context(text, "7.4")
        assert ctx["is_relevant"] is True
        assert ctx["semantic_warning"] is None


# ─── AI Client Tests ──────────────────────────────────────────────────────────

class TestAiClient:
    """Tests for app.modules.analysis.agents.ai_client"""

    def test_clean_json_strips_markdown_fences(self):
        from app.modules.analysis.agents.ai_client import _clean_json
        raw = '```json\n{"score": 0.5}\n```'
        assert _clean_json(raw) == '{"score": 0.5}'

    def test_clean_json_no_fences_unchanged(self):
        from app.modules.analysis.agents.ai_client import _clean_json
        raw = '{"score": 0.5}'
        assert _clean_json(raw) == '{"score": 0.5}'

    def test_call_llm_json_parse_failure_returns_empty(self):
        from app.modules.analysis.agents.ai_client import call_llm_json
        with patch("app.modules.analysis.agents.ai_client.call_llm", return_value="not valid json!!!"):
            result = call_llm_json("test prompt")
            assert result == {}

    def test_call_llm_json_valid_response(self):
        from app.modules.analysis.agents.ai_client import call_llm_json
        fixture = json.dumps({"quote": "Test", "proposed_score": 0.5, "confidence": 0.8})
        with patch("app.modules.analysis.agents.ai_client.call_llm", return_value=fixture):
            result = call_llm_json("test prompt")
            assert result["proposed_score"] == 0.5
            assert result["confidence"] == 0.8


# ─── Prosecution Agent Tests ──────────────────────────────────────────────────

PROSECUTION_FIXTURE = json.dumps({
    "quote": "No personal data shall be transferred to a place outside Malaysia.",
    "citation": "Section 129",
    "criteria_key": "ban_or_local_processing_specific",
    "confidence": 0.9,
    "reasoning": "Section 129 restricts cross-border transfer of personal data."
})

PROSECUTION_FIXTURE_NOT_FOUND = json.dumps({
    "quote": None,
    "citation": None,
    "proposed_score": 0.0,
    "confidence": 0.3,
    "reasoning": "No relevant provision found."
})


class TestProsecutionAgent:
    """Tests for app.modules.analysis.agents.prosecution_agent"""

    def _make_state(self, chunks=None):
        from app.modules.analysis.scoring_engine import VALID_SCORES
        return {
            "country": "Malaysia",
            "indicator_id": "6.1",
            "indicator_title": "Ban/local processing",
            "research_question": "Does Malaysia have a complete ban on cross-border data transfer?",
            "valid_scores": VALID_SCORES["6.1"],
            "chunks": chunks or [{"text": "No personal data shall be transferred to a place outside Malaysia. See Section 129.", "metadata": {"source_url": "https://agc.gov.my/pdpa"}}],
            "prosecution_quote": None, "prosecution_citation": None,
            "prosecution_score": None, "prosecution_confidence": None, "prosecution_reasoning": None,
            "defense_counter_quote": None, "defense_exception_found": False,
            "defense_adjusted_score": None, "defense_confidence": None, "defense_reasoning": None,
            "final_score": None, "act_and_practice": None, "coverage": None,
            "impact_comments": None, "timeframe": None, "references": None, "note": None,
            "final_confidence": None, "final_quote": None, "final_citation": None, "not_found": False,
        }

    def test_prosecution_with_fixture_evidence(self):
        from app.modules.analysis.agents.prosecution_agent import run_prosecution
        with patch("app.modules.analysis.agents.prosecution_agent.call_llm_json",
                   return_value=json.loads(PROSECUTION_FIXTURE)):
            state = self._make_state()
            result = run_prosecution(state)
            assert result["prosecution_score"] == 0.5
            assert result["prosecution_confidence"] == 0.9
            assert "Section 129" in result["prosecution_citation"]

    def test_prosecution_no_chunks_returns_not_found(self):
        from app.modules.analysis.agents.prosecution_agent import run_prosecution
        state = self._make_state(chunks=[])
        result = run_prosecution(state)
        assert result["prosecution_score"] == 0.0
        assert result["prosecution_quote"] is None

    def test_prosecution_score_snapped_to_valid(self):
        from app.modules.analysis.agents.prosecution_agent import run_prosecution
        bad_fixture = json.loads(PROSECUTION_FIXTURE)
        bad_fixture["proposed_score"] = 0.75  # Not valid for 6.1 (which has [1.0, 0.5, 0.0])
        with patch("app.modules.analysis.agents.prosecution_agent.call_llm_json",
                   return_value=bad_fixture):
            state = self._make_state()
            result = run_prosecution(state)
            assert result["prosecution_score"] in [1.0, 0.5, 0.0]


# ─── Arbiter Agent Tests ──────────────────────────────────────────────────────

ARBITER_FIXTURE = json.dumps({
    "criteria_key": "conditions_specific_data",
    "act_and_practice": "Personal Data Protection Act 2010, Section 129",
    "coverage": "Horizontal",
    "impact_comments": "Cross-border transfer of personal data is restricted unless conditions met.",
    "timeframe": "Since 15 November 2013",
    "references": "https://agc.gov.my/akta/vol. 10/act 709 bi.pdf",
    "note": "—",
    "confidence": 0.88,
    "verbatim_quote": "No personal data shall be transferred to a place outside Malaysia.",
    "article_citation": "PDPA 2010, s. 129",
    "not_found": False
})


class TestArbiterAgent:
    """Tests for app.modules.analysis.agents.arbiter_agent"""

    def _make_full_state(self):
        from app.modules.analysis.scoring_engine import VALID_SCORES
        return {
            "country": "Malaysia",
            "indicator_id": "6.4",
            "indicator_title": "Conditional flow regime",
            "research_question": "Is cross-border data transfer allowed under conditions?",
            "valid_scores": VALID_SCORES["6.4"],
            "chunks": [{"text": "Data transfer abroad requires consent.", "metadata": {}}],
            "prosecution_quote": "No personal data shall be transferred outside Malaysia.",
            "prosecution_citation": "PDPA 2010, s. 129",
            "prosecution_score": 0.5,
            "prosecution_confidence": 0.85,
            "prosecution_reasoning": "Section 129 restricts transfer.",
            "defense_counter_quote": None,
            "defense_exception_found": False,
            "defense_adjusted_score": 0.5,
            "defense_confidence": 0.7,
            "defense_reasoning": "No exception found.",
            "final_score": None, "act_and_practice": None, "coverage": None,
            "impact_comments": None, "timeframe": None, "references": None, "note": None,
            "final_confidence": None, "final_quote": None, "final_citation": None, "not_found": False,
        }

    def test_arbiter_produces_final_score(self):
        import asyncio
        from app.modules.analysis.agents.arbiter_agent import run_arbiter
        with patch("app.modules.analysis.agents.arbiter_agent.call_llm_json_async",
                   return_value=json.loads(ARBITER_FIXTURE)):
            state = self._make_full_state()
            result = asyncio.run(run_arbiter(state))
            assert result["final_score"] == 0.5
            assert result["coverage"] == "Horizontal"
            assert result["not_found"] is False

    def test_arbiter_fast_path_not_found(self):
        import asyncio
        from app.modules.analysis.agents.arbiter_agent import run_arbiter
        from app.modules.analysis.scoring_engine import VALID_SCORES
        state = {
            "country": "Australia", "indicator_id": "6.3",
            "indicator_title": "Infrastructure requirement",
            "research_question": "Does Australia require local servers?",
            "valid_scores": VALID_SCORES["6.3"],
            "chunks": [],
            "prosecution_quote": None, "prosecution_citation": None,
            "prosecution_score": 0.0, "prosecution_confidence": 0.2,
            "prosecution_reasoning": "No evidence.",
            "defense_counter_quote": None, "defense_exception_found": False,
            "defense_adjusted_score": 0.0, "defense_confidence": 0.5,
            "defense_reasoning": "Nothing to rebut.",
            "final_score": None, "act_and_practice": None, "coverage": None,
            "impact_comments": None, "timeframe": None, "references": None, "note": None,
            "final_confidence": None, "final_quote": None, "final_citation": None, "not_found": False,
        }
        result = asyncio.run(run_arbiter(state))
        assert result["not_found"] is True
        assert result["final_score"] == 0.0

    # ── Extraction function unit tests ──────────────────────────────────────

    def test_is_valid_law_name_accepts_proper_names(self):
        from app.modules.analysis.agents.arbiter_agent import _is_valid_law_name
        assert _is_valid_law_name("Privacy Act 1988") is True
        assert _is_valid_law_name("Electronic Health Records Act") is True
        assert _is_valid_law_name("Competition and Consumer Act 2010") is True
        assert _is_valid_law_name("General Data Protection Regulation") is True
        assert _is_valid_law_name("Personal Data Protection Act 2012 (Cth)") is True

    def test_is_valid_law_name_rejects_fragments(self):
        from app.modules.analysis.agents.arbiter_agent import _is_valid_law_name
        assert _is_valid_law_name("e are\nrelatively new approaches") is False
        assert _is_valid_law_name("This is a very long text fragment that does not look like a law name at all") is False
        assert _is_valid_law_name("small") is False
        assert _is_valid_law_name("") is False
        assert _is_valid_law_name(None) is False

    def test_extract_law_name_span_finds_proper_name_near_hint(self):
        from app.modules.analysis.agents.arbiter_agent import _extract_law_name_span
        chunk = (
            "These are relatively new approaches. They include the Electronic Health Records Act "
            "in Australia which requires that health record information be protected. "
            "Another law is the Privacy Act 1988 (Cth) which covers all personal data."
        )
        # Hint is the fragment — pattern should extract the clean name
        result = _extract_law_name_span(chunk, "Electronic Health Records Act in Australia")
        assert result == "Electronic Health Records Act"

        # Hint is the year-specific reference
        result = _extract_law_name_span(chunk, "Privacy Act 1988")
        assert result == "Privacy Act 1988 (Cth)"

    def test_extract_law_name_span_returns_none_when_no_pattern(self):
        from app.modules.analysis.agents.arbiter_agent import _extract_law_name_span
        chunk = "This is just a generic discussion about data transfer rules and requirements."
        result = _extract_law_name_span(chunk, "data transfer rules")
        assert result is None

    def test_extract_law_name_span_handles_empty(self):
        from app.modules.analysis.agents.arbiter_agent import _extract_law_name_span
        assert _extract_law_name_span("", "test") is None
        assert _extract_law_name_span("some text", "") is None
        assert _extract_law_name_span("some text", None) is None

    def test_extract_field_programmatically_law_name_with_chunk_index(self):
        from app.modules.analysis.agents.arbiter_agent import _extract_field_programmatically

        chunks = [
            {"text": "The Privacy Act 1988 (Cth) regulates the handling of personal information."},
        ]
        # Valid chunk_index with proper hint
        result = _extract_field_programmatically(
            field_name="act_and_practice",
            field_value="Privacy Act",
            chunk_index=1,
            chunks=chunks,
        )
        assert result == "Privacy Act 1988 (Cth)"

    def test_extract_field_programmatically_rejects_fragment_via_index(self):
        from app.modules.analysis.agents.arbiter_agent import _extract_field_programmatically

        chunks = [
            {"text": "e are\nrelatively new approaches. They include the Electronic Health Records Act "
                      "in Australia which requires that health record information be protected."},
            {"text": "Some other chunk."},
        ]
        # Bad hint from LLM (fragment) — extraction should find clean name
        result = _extract_field_programmatically(
            field_name="act_and_practice",
            field_value="Electronic Health Records Act in Australia which requires that",
            chunk_index=1,
            chunks=chunks,
        )
        assert "Electronic Health Records Act" == result
        # Should NOT contain "e are" or "requires that"
        assert "e are" not in result
        assert "requires that" not in result

    def test_extract_field_programmatically_verification_rejects_bad_name(self):
        from app.modules.analysis.agents.arbiter_agent import _extract_field_programmatically

        chunks = [
            {"text": "These are relatively new approaches to data protection."},
        ]
        # LLM provides a fragment that appears in chunk but is not a valid law name
        result = _extract_field_programmatically(
            field_name="act_and_practice",
            field_value="These are relatively new approaches",
            chunk_index=None,  # Skip strategy 1
            chunks=chunks,
        )
        assert result is None


# ─── Export Tests ─────────────────────────────────────────────────────────────

class TestExporters:
    """Tests for app.modules.output.exporters"""

    def _make_mock_results(self):
        results = []
        for i, (pillar, ind, score) in enumerate([
            (6, "6.1", 0.5), (6, "6.2", 0.0), (7, "7.1", 0.0), (7, "7.4", 0.5)
        ]):
            r = MagicMock()
            r.id = i + 1
            r.pillar_id = pillar
            r.indicator_id = ind
            r.raw_score = score
            r.act_and_practice = f"Test Act for {ind}"
            r.coverage = "Horizontal"
            r.impact_comments = f"Impact comment for {ind}"
            r.timeframe = "Since 2020"
            r.references = "https://example.gov"
            r.note = "—"
            r.confidence = 0.85
            r.verbatim_quote = "Test verbatim quote"
            r.article_citation = f"Act, s.{i+1}"
            r.not_found = False
            r.prosecution_score = score
            r.defense_score = score
            r.arbiter_score = score
            r.discovery_tag = "NEW"
            r.source_pdf_path = None
            r.location_ref = None
            r.law_number_ref = None
            r.processing_time = 1.5
            r.mapping_rationale = f"Maps to {ind} because..."
            results.append(r)
        return results

    def test_export_json_returns_valid_json(self):
        from app.modules.output.exporters import export_json
        results = self._make_mock_results()
        output = export_json(results)
        parsed = json.loads(output)
        assert len(parsed) == 4
        assert parsed[0]["indicator_id"] == "6.1"

    def test_export_csv_returns_bytes_io(self):
        import io
        from app.modules.output.exporters import export_csv
        results = self._make_mock_results()
        buf = export_csv(results, format="rdtii")
        assert isinstance(buf, io.BytesIO)
        content = buf.read().decode("utf-8-sig")
        assert "Pillar_ID" in content
        assert "Raw Score" in content
        assert "6.1" in content

    def test_export_submission_csv_includes_discovery_tag(self):
        import io
        from app.modules.output.exporters import export_csv
        results = self._make_mock_results()
        buf = export_csv(results, format="submission")
        content = buf.read().decode("utf-8-sig")
        assert "Discovery Tag" in content
        assert "Verbatim Snippet" in content
        assert "Mapping Rationale" in content
        assert "NEW" in content

    def test_export_excel_returns_bytes_io(self):
        import io
        from app.modules.output.exporters import export_excel
        results = self._make_mock_results()
        buf = export_excel(results, "Malaysia")
        assert isinstance(buf, io.BytesIO)
        # Verify it's a valid xlsx file by checking file signature
        content = buf.read()
        assert content[:4] == b'PK\x03\x04'  # ZIP/XLSX magic bytes

    def test_export_json_sorted_by_pillar_then_indicator(self):
        from app.modules.output.exporters import export_json
        results = self._make_mock_results()
        parsed = json.loads(export_json(results))
        pillars = [r["pillar_id"] for r in parsed]
        assert pillars == sorted(pillars)

"""Pydantic schemas for API request/response validation."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.config import settings


# ─── Request Schemas ─────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    country: str = Field(..., description="Country name (e.g. Malaysia, Singapore, Australia)")
    pillar_ids: Optional[list[int]] = Field(
        default=None,
        description="Specific pillar IDs to analyse (1-12). NULL = all pillars.",
    )
    indicator_ids: Optional[list[str]] = Field(
        default=None,
        description="Specific indicator IDs to analyse (e.g. ['6.1', '7.1']). NULL = derive from pillar_ids or all.",
    )
    pdf_url: Optional[str] = Field(
        default=None, description="Optional PDF URL to include as a source document."
    )
    llm_provider: str = Field(
        default="auto",
        description="LLM provider: auto | minimax | nvidia | gemini | openai | grok | deepseek | tokenrouter | ollama",
        pattern=r"^(auto|minimax|nvidia|gemini|openai|grok|deepseek|tokenrouter|ollama)$",
    )

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str) -> str:
        supported = [c.strip().title() for c in settings.supported_countries]
        normalised = v.strip().title()
        if normalised not in supported:
            raise ValueError(f"Country must be one of: {supported}")
        return normalised

    @field_validator("pillar_ids")
    @classmethod
    def validate_pillars(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        if v is not None:
            for p in v:
                if p < 1 or p > 12:
                    raise ValueError("Pillar IDs must be between 1 and 12.")
        return v

    @field_validator("indicator_ids")
    @classmethod
    def validate_indicator_ids(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            from app.modules.analysis.scoring_engine import VALID_SCORES
            for ind in v:
                if ind not in VALID_SCORES:
                    raise ValueError(f"Unknown indicator ID: {ind}")
        return v


# ─── Response Schemas ────────────────────────────────────────────────────────

class IndicatorResultSchema(BaseModel):
    """Single indicator result — mirrors the 9-column RDTII output schema + audit trail."""
    id: int
    pillar_id: int
    indicator_id: str
    raw_score: Optional[float]
    act_and_practice: Optional[str]
    coverage: Optional[str]
    impact_comments: Optional[str]
    timeframe: Optional[str]
    references: Optional[str]
    note: Optional[str]
    confidence: Optional[float]
    verbatim_quote: Optional[str]
    article_citation: Optional[str]
    prosecution_score: Optional[float]
    defense_score: Optional[float]
    arbiter_score: Optional[float]
    not_found: bool
    discovery_tag: Optional[str] = None
    source_pdf_path: Optional[str] = None
    location_ref: Optional[str] = None
    processing_time: Optional[float] = None
    mapping_rationale: Optional[str] = None

    model_config = {"from_attributes": True}


class DiscoveredDocumentSchema(BaseModel):
    """Summary of a document found during Module 1 discovery."""
    id: int
    url: str
    title: Optional[str]
    language: Optional[str]
    source_type: str
    enforcement_status: str
    zone1_passed: bool
    indicator_id: Optional[str]
    download_status: str

    model_config = {"from_attributes": True}


class AnalysisRunSchema(BaseModel):
    """Full analysis run with status and results."""
    id: str
    country: str
    status: str
    pillar_ids_requested: Optional[str]
    pdf_url: Optional[str]
    error_message: Optional[str]
    celery_task_id: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    llm_provider: Optional[str] = None
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    indicator_results: list[IndicatorResultSchema] = []
    discovered_documents: list[DiscoveredDocumentSchema] = []

    model_config = {"from_attributes": True}


class AnalysisRunSummarySchema(BaseModel):
    """Lightweight run summary for list endpoint."""
    id: str
    country: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    total_indicators: int
    completed_indicators: int
    error_message: Optional[str] = None
    current_activity: Optional[str] = None
    llm_provider: Optional[str] = None
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None

    model_config = {"from_attributes": True}


class AnalysisSubmitResponse(BaseModel):
    run_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    version: str
    timestamp: datetime


class AuditResponseSchema(BaseModel):
    """Side-by-side audit view: AI extraction vs source document."""
    result_id: int
    run_id: str
    country: str
    indicator_id: str
    pillar_id: int
    raw_score: Optional[float]
    act_and_practice: Optional[str]
    impact_comments: Optional[str]
    verbatim_quote: Optional[str]
    article_citation: Optional[str]
    references: Optional[str]
    confidence: Optional[float]
    not_found: bool
    discovery_tag: Optional[str] = None
    source_documents: list[dict] = []

    model_config = {"from_attributes": True}


class ReviewQueueItemSchema(BaseModel):
    """An indicator result flagged for human review by the Arbiter."""
    result_id: int
    run_id: str
    country: str
    indicator_id: str
    pillar_id: int
    raw_score: Optional[float]
    confidence: Optional[float]
    not_found: bool
    discovery_tag: Optional[str] = None
    prosecution_score: Optional[float]
    defense_score: Optional[float]
    verbatim_quote: Optional[str]
    article_citation: Optional[str]
    impact_comments: Optional[str]
    reason: str = "Confidence below threshold or Arbiter disagreement"

    model_config = {"from_attributes": True}


class AllResultsItemSchema(BaseModel):
    """Single item from the all-results endpoint."""
    id: int
    run_id: str
    country: str
    pillar_id: int
    indicator_id: str
    raw_score: Optional[float] = None
    act_and_practice: Optional[str] = None
    coverage: Optional[str] = None
    impact_comments: Optional[str] = None
    timeframe: Optional[str] = None
    references: Optional[str] = None
    note: Optional[str] = None
    confidence: Optional[float] = None
    verbatim_quote: Optional[str] = None
    article_citation: Optional[str] = None
    discovery_tag: Optional[str] = "NEW"
    location_ref: Optional[str] = None
    mapping_rationale: Optional[str] = None
    created_at: str = ""


class ExportRequest(BaseModel):
    format: str = Field(default="json", pattern="^(json|csv|excel|submission_csv)$")


class RunEventSchema(BaseModel):
    """A single pipeline event for real-time streaming."""
    id: int
    event_type: str
    agent: Optional[str] = None
    indicator_id: Optional[str] = None
    message: str
    data: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RunEventListResponse(BaseModel):
    events: list[RunEventSchema]
    next_offset: int
    has_more: bool


class TokenUsageSchema(BaseModel):
    run_id: str
    country: str
    status: str
    llm_provider: Optional[str] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    indicators_analysed: int = 0

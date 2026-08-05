"""
State definition for the LangGraph agent pipeline.
"""
from typing import TypedDict, Optional


class AnalysisState(TypedDict):
    # Inputs
    country: str
    indicator_id: str
    indicator_title: str
    research_question: str
    valid_scores: list[float]
    chunks: list[dict]  # list of chunk dicts (text, metadata)
    semantic_warning: str  # warning from indicator_mapper, shared across all agents
    
    # Prosecution output
    prosecution_quote: Optional[str]
    prosecution_citation: Optional[str]
    prosecution_score: Optional[float]
    prosecution_criteria_key: Optional[str]
    prosecution_confidence: Optional[float]
    prosecution_reasoning: Optional[str]
    
    # Defense output
    defense_counter_quote: Optional[str]
    defense_exception_found: bool
    defense_adjusted_score: Optional[float]
    defense_criteria_key: Optional[str]
    defense_confidence: Optional[float]
    defense_reasoning: Optional[str]
    
    # Arbiter (Final) output
    final_score: Optional[float]
    final_criteria_key: Optional[str]
    act_and_practice: Optional[str]
    coverage: Optional[str]
    impact_comments: Optional[str]
    timeframe: Optional[str]
    references: Optional[str]
    note: Optional[str]
    final_confidence: Optional[float]
    final_quote: Optional[str]
    final_citation: Optional[str]
    not_found: bool
    law_number_ref: Optional[str]
    location_ref: Optional[str]

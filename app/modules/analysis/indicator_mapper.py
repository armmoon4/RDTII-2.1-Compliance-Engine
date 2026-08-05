"""
Module 2 — Indicator Mapper
Helper functions for mapping semantic context to indicator rules.
Implements the decision tree from RDTII spec §4.3.

Two layers:
  1. map_semantic_context() — advisory warnings injected into LLM prompts
  2. enforce_indicator_rules() — post-LLM PROGRAMMATIC enforcement that
     overrides scores when hard rules are violated (e.g., government data
     scored under Pillar 6). This is the critical fix for hallucination.
"""
import re

def map_semantic_context(text: str, indicator_id: str) -> dict:
    """
    Evaluates the semantic context of a text snippet against the 
    core question for the given indicator.
    
    This helps the Arbiter agent ensure it doesn't fall for keyword traps
    (e.g., scoring a cybersecurity rule as a cross-border data ban).
    """
    text_lower = text.lower()
    context = {
        "is_relevant": True,
        "semantic_warning": None,
    }
    
    # ── Indicators that have exceptions from other pillars ────────────────
    # 3.1 excludes telecom (Pillar 5) and e-commerce (Pillar 12) caps
    if indicator_id == "3.1":
        if "telecom" in text_lower or "telecommunication" in text_lower or "mobile" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Foreign equity limits on the TELECOM sector are excluded from 3.1. "
                "This must be scored under Pillar 5 (indicator 5.2). DO NOT score telecom caps here."
            )
        elif "e-commerce" in text_lower or "ecommerce" in text_lower or "online retail" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Foreign equity limits on E-COMMERCE are excluded from 3.1. "
                "This must be scored under Pillar 12 (indicator 12.01). DO NOT score e-commerce caps here."
            )

    # ── 3.4: Anti-trust M&A is NOT a restriction ───────────────────────────
    elif indicator_id == "3.4":
        if "antitrust" in text_lower or "anti-trust" in text_lower or "competition" in text_lower or "merger" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Anti-trust measures related to M&A are NOT considered a restriction under 3.4, "
                "unless they are discriminatory."
            )

    # ── 6.x: Government data exception (advisory only) ───────────────────
    # Note: Sectoral laws regulating health/financial data SHOULD still score.
    # This warning should only trigger for data that is EXCLUSIVELY about
    # government administrative data (e.g. public sector records, official statistics).
    elif indicator_id in ("6.1", "6.2", "6.3", "6.4"):
        if "government data" in text_lower and "health" not in text_lower and "financial" not in text_lower:
            context["semantic_warning"] = (
                "NOTE: If this measure applies ONLY to government administrative data "
                "(not health, financial, or other sectoral data), it does NOT score under Pillar 6."
            )
        if indicator_id == "6.1" and ("cybersecurity" in text_lower or "security requirement" in text_lower):
            context["semantic_warning"] = (
                "WARNING: Cybersecurity and security requirements are NOT in-scope for indicator 6.1 "
                "(cross-border transfer of personal data). This should not be scored under 6.1 "
                "unless it explicitly restricts cross-border data flows."
            )

    # ── 7.3: Only MINIMUM retention scores, not MAXIMUM ────────────────────
    elif indicator_id == "7.3":
        if "maximum" in text_lower or "longer than necessary" in text_lower or "not exceed" in text_lower or "longer than" in text_lower:
            context["semantic_warning"] = (
                "WARNING: This appears to be a MAXIMUM retention period or purpose-limitation rule. "
                "Indicator 7.3 only scores MINIMUM retention requirements."
            )
        elif "delete after" in text_lower or "destroy after" in text_lower or "erasure" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Deletion/destruction obligations are MAXIMUM retention limits, "
                "not MINIMUM requirements. Does NOT score under 7.3."
            )

    # ── 9.1: Only commercial content blocking scores ───────────────────────
    elif indicator_id == "9.1":
        if "pornography" in text_lower or "defamation" in text_lower or "criminal" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Blocking of illegal/political/adult/defamatory content "
                "does NOT score under 9.1. Only commercial content blocking scores."
            )
        elif "child" in text_lower or "terrorism" in text_lower or "national security" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Blocking of criminal/illegal content (child pornography, terrorism, national security) "
                "is internationally agreed and does NOT score under 9.1."
            )

    # ── 9.3: Misleading advertising exceptions ────────────────────────────
    elif indicator_id == "9.3":
        if "misleading" in text_lower or "false advertising" in text_lower or "deceptive" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Requirements that advertising should not be misleading "
                "are EXCLUDED from scoring under 9.3. Look for broader restrictions."
            )

    # ── 9.4: Telecom/e-commerce licenses are excluded ──────────────────────
    elif indicator_id == "9.4":
        if "telecommunication" in text_lower or "telecom licence" in text_lower or "carrier licence" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Licenses for telecommunication facilities and service providers "
                "are covered under Pillar 5, NOT under 9.4."
            )
        elif "e-commerce" in text_lower or "ecommerce platform" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Licenses for e-commerce platforms are covered under Pillar 12, "
                "NOT under 9.4."
            )

    # ── 12.2: Consumer protection exceptions ──────────────────────────────
    elif indicator_id == "12.2":
        if "alcohol" in text_lower or "tobacco" in text_lower or "pharmaceutical" in text_lower or "medicinal" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Limitations on online purchases/delivery of alcoholic beverages, "
                "tobacco, and pharmaceuticals related to consumer protection "
                "are EXCLUDED from scoring under 12.2."
            )

    # ── 12.3: Excludes payment/delivery licenses ───────────────────────────
    elif indicator_id == "12.3":
        if "payment" in text_lower or "delivery" in text_lower or "courier" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Licenses pertaining to online payment services or delivery "
                "are EXCLUDED from 12.3. This indicator only covers licenses for e-commerce providers (B2B/B2C)."
            )

    # ── 12.4.x: All payment limitations ───────────────────────────────────
    elif indicator_id.startswith("12.4"):
        if "consumer protection" in text_lower or "anti-fraud" in text_lower or "anti money laundering" in text_lower:
            context["semantic_warning"] = (
                "WARNING: Verify this is a genuine trade restriction and not a standard "
                "consumer protection or AML/CFT measure."
            )

    return context


def enforce_indicator_rules(
    indicator_id: str,
    act_and_practice: str | None,
    final_quote: str | None,
    final_score: float,
) -> dict:
    """
    POST-LLM enforced rules layer.
    
    Unlike map_semantic_context() which only issues advisory warnings to the LLM,
    this function PROGRAMMATICALLY overrides scores when hard rules are violated.
    
    Returns an override dict:
      {"override": bool, "new_score": float, "new_not_found": bool, "note": str}
    
    If override is False, the result passes through unchanged.
    """
    override = {
        "override": False,
        "new_score": final_score,
        "new_not_found": False,
        "note": None,
    }

    text_lower = (act_and_practice or "").lower() + " " + (final_quote or "").lower()

    # ── Pillar 7.3: Maximum retention does NOT score ───────────────────
    if indicator_id == "7.3":
        if re.search(r"\bmaximum\b|\blonger than necessary\b|\bnot exceed\b|\bdelete after\b|\bdestroy after\b|\berasure\b", text_lower):
            if final_score > 0.0:
                override["override"] = True
                override["new_score"] = 0.0
                override["new_not_found"] = True
                override["note"] = (
                    f"ENFORCED RULE: Indicator 7.3 only scores MINIMUM retention. "
                    f"LLM scored {final_score} but text refers to maximum retention or deletion. Score overridden to 0.0."
                )

    # ── Pillar 9.1: Non-commercial content blocking does NOT score ─────
    if indicator_id == "9.1":
        if re.search(r"\bchild\b|\bterrorism\b|\bnational security\b|\bpornography\b|\bdefamation\b|\bcriminal\b", text_lower):
            if final_score > 0.0:
                override["override"] = True
                override["new_score"] = 0.0
                override["new_not_found"] = True
                override["note"] = (
                    f"ENFORCED RULE: Indicator 9.1 only scores blocking of COMMERCIAL content. "
                    f"LLM scored {final_score} but text refers to non-commercial blocking. Score overridden to 0.0."
                )

    # ── Pillar 9.3: Misleading advertising does NOT score ──────────────
    if indicator_id == "9.3":
        if re.search(r"\bmisleading\b|\bfalse advertising\b|\bdeceptive\b", text_lower):
            if final_score > 0.0:
                override["override"] = True
                override["new_score"] = 0.0
                override["new_not_found"] = True
                override["note"] = (
                    f"ENFORCED RULE: Indicator 9.3 EXCLUDES misleading/false advertising rules. "
                    f"LLM scored {final_score} but text references advertising standards. Score overridden to 0.0."
                )

    # ── Pillar 12.2: Alcohol/tobacco/pharmaceutical exceptions ─────────
    if indicator_id == "12.2":
        if re.search(r"\balcohol\b|\btobacco\b|\bpharmaceutical\b|\bmedicinal\b", text_lower):
            if final_score > 0.0:
                override["override"] = True
                override["new_score"] = 0.0
                override["new_not_found"] = True
                override["note"] = (
                    f"ENFORCED RULE: Indicator 12.2 EXCLUDES alcohol/tobacco/pharmaceutical "
                    f"consumer protection measures. LLM scored {final_score}. Score overridden to 0.0."
                )

    return override

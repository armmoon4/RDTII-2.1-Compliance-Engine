"""
Module 2 — Scoring Engine
Hardcoded valid score sets for all 61 RDTII 2.1 indicators according to spec §5.
Includes SCORE_CRITERIA — a deterministic mapping from factual conditions to scores.
"""

# Valid score sets for all 61 indicators mapped to their criteria bounds
VALID_SCORES: dict[str, list[float]] = {
    # Pillar 1
    "1.4": [1.0, 0.75, 0.5, 0.25, 0.0],
    # Pillar 2
    "2.1": [1.0, 0.5, 0.0],
    "2.2": [1.0, 0.5, 0.0],
    "2.3": [1.0, 0.5, 0.0],
    # Pillar 3
    "3.1": [1.0, 0.8, 0.5, 0.0],
    "3.2": [1.0, 0.0],
    "3.3": [1.0, 0.0],
    "3.4": [1.0, 0.5, 0.25, 0.0],
    "3.5": [1.0, 0.0],
    # Pillar 4
    "4.01": [1.0, 0.5, 0.0],
    "4.2": [1.0, 0.5, 0.0],
    "4.3": [1.0, 0.5, 0.0],
    "4.5": [1.0, 0.5, 0.0],
    "4.6": [1.0, 0.5, 0.0],
    "4.9": [1.0, 0.5, 0.0],
    "4.10": [1.0, 0.5, 0.0],
    # Pillar 5
    "5.1": [1.0, 0.5, 0.0],
    "5.2": [1.0, 0.8, 0.5, 0.0],
    "5.3": [1.0, 0.5, 0.0],
    "5.4": [1.0, 0.5, 0.25, 0.0],
    "5.5": [1.0, 0.0],
    "5.7": [1.0, 0.0],
    # Pillar 6
    "6.1": [1.0, 0.5, 0.0],
    "6.2": [1.0, 0.5, 0.0],
    "6.3": [1.0, 0.0],
    "6.4": [1.0, 0.5, 0.0],
    # Pillar 7
    "7.1": [1.0, 0.5, 0.0],
    "7.2": [1.0, 0.5, 0.0],
    "7.3": [1.0, 0.0],
    "7.4": [1.0, 0.5, 0.0],
    "7.5": [1.0, 0.0],
    # Pillar 8
    "8.1": [1.0, 0.5, 0.0],
    "8.2": [1.0, 0.5, 0.0],
    "8.3": [1.0, 0.5, 0.0],
    "8.4": [1.0, 0.5, 0.0],
    # Pillar 9
    "9.1": [1.0, 0.5, 0.0],
    "9.3": [1.0, 0.0],
    "9.4": [1.0, 0.5, 0.0],
    # Pillar 10
    "10.1": [1.0, 0.5, 0.0],
    "10.2": [1.0, 0.5, 0.0],
    "10.3": [1.0, 0.5, 0.0],
    "10.4": [1.0, 0.0],
    # Pillar 11
    "11.1": [1.0, 0.0],
    "11.2": [1.0, 0.5, 0.0],
    "11.3": [1.0, 0.5, 0.0],
    "11.4": [1.0, 0.0],
    # Pillar 12
    "12.01": [1.0, 0.5, 0.0],
    "12.2": [1.0, 0.0],
    "12.3": [1.0, 0.0],
    "12.4.1": [1.0, 0.0],
    "12.4.2": [1.0, 0.0],
    "12.4.3": [1.0, 0.0],
    "12.4.4": [1.0, 0.0],
    "12.4.5": [1.0, 0.0],
    "12.4.6": [1.0, 0.0],
    "12.4.7": [1.0, 0.0],
    "12.5": [1.0, 0.5, 0.0],
    "12.6": [1.0, 0.5, 0.0],
    "12.7": [1.0, 0.5, 0.0],
    "12.8": [1.0, 0.0],
    "12.9": [1.0, 0.0],
}


# ─── Criteria-to-Score Mapping ───────────────────────────────────────────────
# Each entry is a list of (condition_key, description, score) tuples.
# The LLM identifies which condition applies; code maps it to the score.
# This eliminates LLM numerical score guessing.

SCORE_CRITERIA: dict[str, list[tuple[str, str, float]]] = {
    # ── Pillar 1: Tariffs and Trade Defence ────────────────────────────────
    "1.4": [
        ("more_than_three_measures", "More than three measures", 1.0),
        ("three_measures", "Three measures", 0.75),
        ("two_measures", "Two measures", 0.5),
        ("one_measure", "One measure", 0.25),
        ("no_measure", "No measure", 0.0),
    ],
    # ── Pillar 2: Public Procurement ───────────────────────────────────────
    "2.1": [
        ("any_circumstances_or_multiple", "Legislative measure excludes foreign firms under any circumstances, or more than one measure excluding a specific group", 1.0),
        ("specific_group_excluded", "Legislative measure excludes a specific (group of) foreign firm(s)", 0.5),
        ("no_measure_or_power_granted", "No measure (only a legal basis granting power to exclude)", 0.0),
    ],
    "2.2": [
        ("surrender_patents_source_code_trade_secrets", "Requirement to surrender patents, source codes or trade secrets to participate in tenders", 1.0),
        ("specific_encryption_requirement", "Requirement to use specific encryption to win tenders", 0.5),
        ("no_measure", "No measure", 0.0),
    ],
    "2.3": [
        ("direct_discrimination_or_multiple", "Direct discrimination against foreign bidders, or more than one measure applying to all bidders", 1.0),
        ("applies_to_all_bidders", "Measure applies to all bidders (e.g., local content, performance conditions)", 0.5),
        ("no_measure_or_power_granted", "No measure (only a legal basis granting power to impose limitations)", 0.0),
    ],
    # ── Pillar 3: Foreign Direct Investment ────────────────────────────────
    "3.1": [
        ("ban_or_minority_in_multiple_sectors", "Ban (0%) in at least one sector, or minority stake in more than one sector", 1.0),
        ("minority_stake_one_sector", "Minority stake (1-50%) allowed in one sector", 0.8),
        ("controlling_stake_or_soe", "Controlling stake (51-99%) allowed, or restrictions only in SOEs", 0.5),
        ("full_ownership", "Full ownership (100%) allowed in sectors relevant for digital trade", 0.0),
    ],
    "3.2": [
        ("any_measure", "Any joint venture requirement", 1.0),
        ("no_measure", "No measure", 0.0),
    ],
    "3.3": [
        ("any_measure", "Any nationality or residency requirement for board of directors or managers", 1.0),
        ("no_measure", "No measure", 0.0),
    ],
    "3.4": [
        ("used_to_block_investment", "Screening mechanism has been used to block an investment in digital trade", 1.0),
        ("two_or_more_mechanisms", "Two or more investment screening mechanisms", 0.5),
        ("one_screening_mechanism", "A screening mechanism", 0.25),
        ("no_screening", "No screening mechanism", 0.0),
    ],
    "3.5": [
        ("any_measure", "Any commercial presence requirement to offer cross-border digital services", 1.0),
        ("no_measure", "No measure", 0.0),
    ],
    # ── Pillar 4: Intellectual Property Rights ─────────────────────────────
    "4.01": [
        ("differential_treatment_or_rejection", "Differential treatment of foreign firms, local representative requirement, or discriminatory patent rejection", 1.0),
        ("non_transparent_or_high_costs", "Non-transparent process, high fees/costs, substantive examination, or requirement to file locally first", 0.5),
        ("no_restriction", "No restriction", 0.0),
    ],
    "4.2": [
        ("absence_of_remedies_and_provisional", "Absence of civil/admin remedies AND provisional measures", 1.0),
        ("remedies_or_provisional", "Adopts civil/admin remedies OR provisional measures", 0.5),
        ("remedies_and_provisional", "Adopts civil/admin remedies AND provisional measures", 0.0),
    ],
    "4.3": [
        ("high_impact_or_multiple", "High-impact restriction affecting all circumstances/sectors, or more than one limited-impact restriction", 1.0),
        ("limited_impact", "Limited-impact restriction affecting a specific circumstance or sector", 0.5),
        ("no_restriction", "No restriction", 0.0),
    ],
    "4.5": [
        ("no_framework_or_no_exceptions", "Lack of copyright legal framework or lack of copyright exceptions", 1.0),
        ("unclear_exceptions", "Unclear copyright exceptions (e.g., three-step test ambiguity)", 0.5),
        ("clear_fair_use_or_dealing", "Clear copyright exceptions following fair use or fair dealing model", 0.0),
    ],
    "4.6": [
        ("absence_of_remedies_and_provisional", "Absence of civil/admin remedies AND provisional measures for online copyright", 1.0),
        ("remedies_or_provisional", "Adopts civil/admin remedies OR provisional measures", 0.5),
        ("remedies_and_provisional", "Adopts civil/admin remedies AND provisional measures", 0.0),
    ],
    "4.9": [
        ("sector_wide_horizontal_or_multiple", "Disclosure requirement affecting entire sector or all sectors, or more than one limited-impact measure", 1.0),
        ("limited_impact_disclosure", "Disclosure requirement of limited impact (e.g., court order, regulatory proceedings)", 0.5),
        ("no_measure_or_public_interest_safeguards", "No measure, or disclosure only for public interest with safeguards", 0.0),
    ],
    "4.10": [
        ("no_effective_framework", "Lack of effective trade secrets legal framework", 1.0),
        ("limited_practice_or_scope", "Limited practice/scope addressing trade secrets protection", 0.5),
        ("effective_protection", "Presence of effective trade secrets protection in any form", 0.0),
    ],
    # ── Pillar 5: Telecom Regulations & Competition ────────────────────────
    "5.1": [
        ("no_sharing_obligation", "No passive infrastructure sharing obligation", 1.0),
        ("not_mandated_but_practiced", "Passive sharing is not mandated but practiced in the market", 0.5),
        ("sharing_mandated", "Passive sharing is mandated", 0.0),
    ],
    "5.2": [
        ("ban_or_minority_in_multiple", "Ban (0%) or minority stake in more than one measure", 1.0),
        ("minority_stake", "Minority stake (1-50%) allowed", 0.8),
        ("controlling_stake_or_soe", "Controlling stake (51-99%) allowed, or restrictions only in SOEs", 0.5),
        ("full_ownership", "Full ownership (100%) allowed in telecom sector", 0.0),
    ],
    "5.3": [
        ("majority_government_owned_or_multiple", "At least one company with government shares >50%, or more than one company with minority shares", 1.0),
        ("minority_government_owned", "One company with government shares between 1% and 50%", 0.5),
        ("no_government_shares", "No shares owned by the government in telecom companies", 0.0),
    ],
    "5.4": [
        ("no_separation_mandated", "No functional/accounting separation mandated", 1.0),
        ("accounting_separation_only", "Only accounting separation is mandated", 0.5),
        ("functional_separation_only", "Only functional separation is mandated", 0.25),
        ("both_separations_mandated", "Both accounting and functional separations are mandated", 0.0),
    ],
    "5.5": [
        ("strict_licensing_scheme", "Strict licensing scheme (discrimination, minimum capital, mandatory performance requirements)", 1.0),
        ("no_strict_licensing", "No strict licensing scheme", 0.0),
    ],
    "5.7": [
        ("no_independent_authority", "No independent telecom authority", 1.0),
        ("independent_authority_exists", "Independent telecom authority is established", 0.0),
    ],
    # ── Pillar 6: Cross-border Data Policies ───────────────────────────────
    "6.1": [
        ("ban_or_local_processing_all_or_personal", "Ban/local processing for all sectors or personal data, or more than one specific-sector measure", 1.0),
        ("ban_or_local_processing_specific", "Ban/local processing for a specific sector, specific data type, non-personal data, or one country", 0.5),
        ("no_requirement", "No requirement", 0.0),
    ],
    "6.2": [
        ("local_storage_all_or_personal", "Local storage requirement for all sectors or personal data, or more than one specific-sector measure", 1.0),
        ("local_storage_specific", "Local storage requirement for a specific sector, specific data type, or non-personal data", 0.5),
        ("no_requirement", "No requirement", 0.0),
    ],
    "6.3": [
        ("infrastructure_requirement", "Infrastructure requirement (local servers/data centres)", 1.0),
        ("no_requirement", "No requirement", 0.0),
    ],
    "6.4": [
        ("conditions_all_sectors_or_personal", "Conditions for all sectors or personal data", 1.0),
        ("conditions_specific_data", "Conditions for specific data or non-personal data", 0.5),
        ("no_condition", "No condition", 0.0),
    ],
    # ── Pillar 7: Domestic Data Protection & Privacy ───────────────────────
    "7.1": [
        ("no_framework", "No data protection legal framework", 1.0),
        ("sectoral_framework", "Data protection framework only for specific sectors", 0.5),
        ("comprehensive_framework", "Comprehensive data protection framework", 0.0),
    ],
    "7.2": [
        ("no_framework", "No cybersecurity legal framework", 1.0),
        ("non_dedicated_or_sectoral", "Non-dedicated framework or sectoral cybersecurity law", 0.5),
        ("dedicated_horizontal_framework", "Dedicated horizontal cybersecurity legal framework", 0.0),
    ],
    "7.3": [
        ("minimum_retention_required", "Minimum period of data retention requirement", 1.0),
        ("no_requirement", "No data retention requirement", 0.0),
    ],
    "7.4": [
        ("dpo_or_dpia_all_sectors", "DPO and/or DPIA requirement applied to all sectors", 1.0),
        ("dpo_or_dpia_specific_sector", "DPO and/or DPIA requirement applied to a specific sector", 0.5),
        ("no_requirement", "No requirement", 0.0),
    ],
    "7.5": [
        ("government_access_without_court_order", "Any measure allowing government data access without court orders", 1.0),
        ("no_measure", "No measure", 0.0),
    ],
    # ── Pillar 8: Internet Intermediary Liability ──────────────────────────
    "8.1": [
        ("no_framework", "No intermediary liability framework for copyright", 1.0),
        ("sectoral_framework", "Sectoral framework limiting intermediary liability for copyright", 0.5),
        ("horizontal_framework", "Horizontal framework limiting intermediary liability for copyright", 0.0),
    ],
    "8.2": [
        ("no_framework", "No intermediary liability framework for other illegal activities", 1.0),
        ("sectoral_framework", "Sectoral framework limiting intermediary liability", 0.5),
        ("horizontal_framework", "Horizontal framework limiting intermediary liability", 0.0),
    ],
    "8.3": [
        ("identity_for_internet_or_online_services", "User identity required to connect to the internet or access online services", 1.0),
        ("sim_registration_only", "Identity requirement for SIM registration only", 0.5),
        ("no_restrictions", "No restrictions", 0.0),
    ],
    "8.4": [
        ("monitoring_with_removal_or_blocking", "Any monitoring requirement with obligation to remove or block content", 1.0),
        ("active_monitoring_only", "Requirement for active monitoring of user activities without removal obligation", 0.5),
        ("no_measure", "No measure", 0.0),
    ],
    # ── Pillar 9: Content Access ───────────────────────────────────────────
    "9.1": [
        ("any_blocking", "Any blocking of commercial web content", 1.0),
        ("any_filtering", "Any filtering of commercial web content", 0.5),
        ("no_blocking_or_filtering", "No blocking or filtering (except illegal content)", 0.0),
    ],
    "9.3": [
        ("any_restriction", "Any restriction on online advertising", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "9.4": [
        ("strict_licence_or_multiple", "Strict licence requirement, or more than one licensing measure", 1.0),
        ("any_licensing_scheme", "Any licensing scheme for online content providers", 0.5),
        ("no_restriction", "No restriction", 0.0),
    ],
    # ── Pillar 10: Non-technical NTMs ──────────────────────────────────────
    "10.1": [
        ("ban_on_multiple", "Ban on more than one ICT good or digital service", 1.0),
        ("ban_on_one_product", "Ban on one specific product or service", 0.5),
        ("no_measure", "No measure", 0.0),
    ],
    "10.2": [
        ("blocking_restrictions_or_multiple", "Import restrictions that potentially block trade (e.g., quotas), or at least two compliance-cost measures", 1.0),
        ("compliance_cost_restrictions", "Import restrictions adding compliance costs (licences, permits, labelling)", 0.5),
        ("no_restriction", "No restriction", 0.0),
    ],
    "10.3": [
        ("sectoral_horizontal_or_multiple_product", "LCR at sectoral/horizontal (HS-4/HS-2) level, or at least two product-level LCRs", 1.0),
        ("product_level_lcr", "LCR at product level (HS-6/HS-8)", 0.5),
        ("no_measure", "No measure", 0.0),
    ],
    "10.4": [
        ("any_restriction", "Any export restriction on ICT goods or online services", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    # ── Pillar 11: Standards and Procedures ────────────────────────────────
    "11.1": [
        ("foreigners_excluded_or_non_transparent", "Foreigners not allowed in standard-setting bodies, or non-transparent standard-setting", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "11.2": [
        ("sdoc_not_allowed_no_third_party_mra", "SDoC not allowed and third-party certification only from countries with MRA", 1.0),
        ("sdoc_not_allowed_third_party_mra", "SDoC not allowed, but third-party certification accepted from CABs via MRA", 0.5),
        ("sdoc_allowed", "SDoC allowed for foreign businesses", 0.0),
    ],
    "11.3": [
        ("mandatory_screening_no_third_party", "Mandatory product screening/testing in place, no third-party acceptance", 1.0),
        ("screening_with_third_party", "Measure in place but accepts third-party testing results", 0.5),
        ("no_requirement", "No requirement", 0.0),
    ],
    "11.4": [
        ("any_deviation", "Any deviation from international encryption standards (ISO, IEC, ITU, FIPS, AES, etc.)", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    # ── Pillar 12: Online Sales and Transactions ───────────────────────────
    "12.01": [
        ("minority_stake", "Minority stake (1-50%) allowed in e-commerce", 1.0),
        ("controlling_stake", "Controlling stake (51-99%) allowed in e-commerce", 0.5),
        ("full_ownership", "Full ownership (100%) allowed in e-commerce sector", 0.0),
    ],
    "12.2": [
        ("limits_on_purchases_and_delivery", "Limits on number of products for online purchase AND delivery restrictions", 1.0),
        ("no_measure", "No measure", 0.0),
    ],
    "12.3": [
        ("any_license", "Any license requirement for e-commerce providers", 1.0),
        ("no_license", "No license required", 0.0),
    ],
    "12.4.1": [
        ("local_bank_account_required", "Requirement to use a local bank account for online payments", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.4.2": [
        ("currency_required", "Requirement on currency used for international payments", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.4.3": [
        ("deviant_national_standards", "National payment security standards deviating from international standards", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.4.4": [
        ("restrictive_licensing", "Licensing requirements with restrictive conditions for payment services", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.4.5": [
        ("ceiling_exists", "Ceiling on maximum amount payable by electronic payment methods", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.4.6": [
        ("mandatory_intermediary", "Requirement mandating specific intermediaries for online payments", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.4.7": [
        ("other_restrictions", "Other restrictions on online payments", 1.0),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.5": [
        ("no_de_minimis", "No De Minimis threshold", 1.0),
        ("below_200_usd", "De Minimis below 200 USD", 0.5),
        ("at_or_above_200_usd", "De Minimis at or above 200 USD", 0.0),
    ],
    "12.6": [
        ("duties_imposed", "Customs duties imposed on electronic transmissions", 1.0),
        ("legal_mechanism_to_impose", "Legal mechanism or regulations applicable to impose customs duties on electronic transmissions", 0.5),
        ("no_restriction", "No restriction (moratorium on customs duties)", 0.0),
    ],
    "12.7": [
        ("physical_presence_required", "Physical presence required to register local domain name for e-retail", 1.0),
        ("local_representative_required", "Local representative required for domain name registration", 0.5),
        ("no_restriction", "No restriction", 0.0),
    ],
    "12.8": [
        ("local_presence_required", "Local presence requirement for at least one sector", 1.0),
        ("no_requirement", "No requirement", 0.0),
    ],
    "12.9": [
        ("no_consumer_protection_framework", "No consumer protection legal framework applicable to online commerce", 1.0),
        ("framework_exists", "Consumer protection law applicable to online commerce", 0.0),
    ],
}


def validate_score(indicator_id: str, score: float) -> float:
    """
    Ensure the proposed score exists in the valid score set for the indicator.
    If not, snaps to the closest valid score.
    """
    valid_set = VALID_SCORES.get(indicator_id)
    if not valid_set:
        raise ValueError(f"Unknown indicator ID: {indicator_id}")

    # Snap to closest valid score
    closest_score = min(valid_set, key=lambda x: abs(x - score))
    return float(closest_score)


def criteria_to_score(indicator_id: str, criteria_key: str) -> float | None:
    """
    Map a criteria key to its corresponding score for the given indicator.
    Returns None if the key is not found.
    """
    criteria_list = SCORE_CRITERIA.get(indicator_id)
    if not criteria_list:
        return None
    for key, _, score in criteria_list:
        if key == criteria_key:
            return score
    return None


def get_criteria_keys(indicator_id: str) -> list[str]:
    """Return all valid criteria keys for an indicator."""
    criteria_list = SCORE_CRITERIA.get(indicator_id)
    if not criteria_list:
        return []
    return [key for key, _, _ in criteria_list]


def format_criteria_for_prompt(indicator_id: str) -> str:
    """
    Format the scoring criteria table as human-readable text for LLM prompts.
    """
    criteria_list = SCORE_CRITERIA.get(indicator_id)
    if not criteria_list:
        return ""

    lines = ["SCORING CRITERIA (identify which condition matches the evidence):",
             "Key | Condition | Score"]
    for i, (key, desc, score) in enumerate(criteria_list, 1):
        lines.append(f"{i}. {key} | {desc} | {score}")
    lines.append("")
    lines.append("IMPORTANT: Select the KEY (e.g. '{0}') that best matches the evidence.".format(
        criteria_list[0][0]))
    lines.append("The numeric score will be assigned automatically based on your key selection.")
    lines.append("")
    return "\n".join(lines)


def get_indicator_ids_for_pillars(pillar_ids: list[int] | None) -> list[str]:
    """Return all indicator IDs that belong to the requested pillars."""
    all_indicators = list(VALID_SCORES.keys())
    if not pillar_ids:
        return all_indicators

    filtered = []
    for ind in all_indicators:
        prefix = ind.split(".")[0]
        if int(prefix) in pillar_ids:
            filtered.append(ind)

    return filtered

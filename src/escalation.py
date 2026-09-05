from . import rules as rules_module

REASON_RED_FLAG = "red_flag"
REASON_MULTI_RULE = "multi_rule_ambiguity"
REASON_LOW_CONFIDENCE = "persistent_low_confidence"
REASON_API_FAILURE = "api_failure"


def _check_red_flags(condition_key: str, fields: dict) -> tuple[bool, str | None]:
    cond = rules_module.get_condition(condition_key)
    for rf in cond["red_flag_fields"]:
        fname = rf["name"]
        entry = fields.get(fname, {})
        value = entry.get("value")
        confidence = entry.get("confidence", 0.0)
        if value is True and confidence >= rules_module.CONFIDENCE_GRAY_ZONE_LOW:
            return True, rf["description"]
    return False, None


def _condition_is_plausible(condition_key: str, fields: dict) -> bool:
    field_map = fields.get(condition_key, {})
    cond = rules_module.get_condition(condition_key)
    confident_count = sum(
        1
        for req in cond["required_fields"]
        if field_map.get(req["name"], {}).get("confidence", 0) >= rules_module.CONFIDENCE_GRAY_ZONE_LOW
        and field_map.get(req["name"], {}).get("value") is not None
    )
    return confident_count >= max(1, len(cond["required_fields"]) // 2)


def check_escalation(
    relevant_conditions: list[str],
    extracted_fields: dict,
    followup_count: int,
) -> dict:
    for condition_key in relevant_conditions:
        fields_for_cond = extracted_fields.get(condition_key, {})
        triggered, description = _check_red_flags(condition_key, fields_for_cond)
        if triggered:
            cond = rules_module.get_condition(condition_key)
            return {
                "should_escalate": True,
                "reason": REASON_RED_FLAG,
                "reason_message": (
                    f"A critical symptom was identified: {description}. "
                    f"This case requires immediate human assessment — rule {cond['id']}."
                ),
            }

    if len(relevant_conditions) > 1:
        plausible = [c for c in relevant_conditions if _condition_is_plausible(c, extracted_fields)]
        if len(plausible) > 1:
            condition_names = ", ".join(
                rules_module.get_condition(c)["display_name"] for c in plausible
            )
            return {
                "should_escalate": True,
                "reason": REASON_MULTI_RULE,
                "reason_message": (
                    f"Multiple conditions appear plausible ({condition_names}). "
                    "A human clinician is required to differentiate."
                ),
            }

    if followup_count >= rules_module.FOLLOWUP_CAP:
        return {
            "should_escalate": True,
            "reason": REASON_LOW_CONFIDENCE,
            "reason_message": (
                "Sufficient information could not be gathered after the maximum number of "
                "follow-up questions. A human clinician should assess this case."
            ),
        }

    return {"should_escalate": False}

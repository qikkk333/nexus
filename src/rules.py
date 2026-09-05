import yaml
import os
from pathlib import Path

_RULES_PATH = Path(__file__).parent.parent / "data" / "triage_rules.yaml"

with open(_RULES_PATH, "r") as f:
    _RULES = yaml.safe_load(f)

_thresholds = _RULES["confidence_thresholds"]

CONFIDENCE_USABLE: float = _thresholds["usable"]
CONFIDENCE_GRAY_ZONE_LOW: float = _thresholds["gray_zone_low"]
CONFIDENCE_GRAY_ZONE_HIGH: float = _thresholds["gray_zone_high"]
FOLLOWUP_CAP: int = _thresholds["followup_cap"]

URGENCY_LEVELS = ["IMMEDIATE", "URGENT", "ROUTINE"]

CONDITIONS: dict = _RULES["conditions"]


def get_condition(condition_key: str) -> dict:
    if condition_key not in CONDITIONS:
        raise KeyError(f"Unknown condition: {condition_key}")
    return CONDITIONS[condition_key]


def get_relevant_conditions(text: str) -> list[str]:
    text_lower = text.lower()
    matched = []
    for key, cond in CONDITIONS.items():
        for keyword in cond["keywords"]:
            if keyword in text_lower:
                matched.append(key)
                break
    return matched


def get_all_fields_for_condition(condition_key: str) -> list[dict]:
    cond = get_condition(condition_key)
    return cond["required_fields"] + cond["red_flag_fields"]


def _eval_expression(expr: str, fields: dict) -> bool:
    if expr == "default":
        return True
    namespace = {}
    for name, data in fields.items():
        namespace[name] = data.get("value")
    namespace["True"] = True
    namespace["False"] = False
    try:
        return bool(eval(expr, {"__builtins__": {}}, namespace))
    except (TypeError, NameError, ZeroDivisionError, ValueError):
        return False


def match_rule(condition_key: str, fields: dict) -> dict:
    cond = get_condition(condition_key)
    for level in cond["urgency_levels"]:
        for expr in level["expressions"]:
            if _eval_expression(expr, fields):
                return {
                    "rule_id": cond["id"],
                    "condition_key": condition_key,
                    "urgency": level["urgency"],
                    "department": level["department"],
                    "rule_text": level["rule_text"],
                }
    last = cond["urgency_levels"][-1]
    return {
        "rule_id": cond["id"],
        "condition_key": condition_key,
        "urgency": last["urgency"],
        "department": last["department"],
        "rule_text": last["rule_text"],
    }


def check_fields_ready(condition: dict, fields: dict) -> tuple[bool, list[dict]]:
    issues = []
    for req in condition["required_fields"]:
        fname = req["name"]
        entry = fields.get(fname, {})
        value = entry.get("value")
        confidence = entry.get("confidence", 0.0)
        if value is None or confidence < CONFIDENCE_GRAY_ZONE_LOW:
            issues.append({"field": req, "reason": "missing", "confidence": confidence})
        elif confidence < CONFIDENCE_USABLE:
            issues.append({"field": req, "reason": "gray_zone", "confidence": confidence})
    return len(issues) == 0, issues


def get_leading_condition(relevant_conditions: list[str], extracted_fields: dict) -> str:
    if len(relevant_conditions) == 1:
        return relevant_conditions[0]
    best_key = relevant_conditions[0]
    best_score = -1
    for key in relevant_conditions:
        fields = extracted_fields.get(key, {})
        score = sum(
            1
            for f in fields.values()
            if f.get("confidence", 0) > 0.5 and f.get("value") is not None
        )
        if score > best_score:
            best_score = score
            best_key = key
    return best_key

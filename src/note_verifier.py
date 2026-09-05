from . import rules as rules_module

ALL_URGENCY_LEVELS = rules_module.URGENCY_LEVELS


def verify(note_text: str, matched_rule: dict) -> tuple[bool, list[str]]:
    expected_urgency = matched_rule["urgency"]
    expected_department = matched_rule["department"]
    expected_rule_id = matched_rule["rule_id"]

    note_upper = note_text.upper()
    issues = []

    if expected_urgency not in note_upper:
        issues.append(
            f"Expected urgency '{expected_urgency}' not found in note text."
        )

    if expected_department.upper() not in note_upper:
        issues.append(
            f"Expected department '{expected_department}' not found in note text."
        )

    if expected_rule_id not in note_text:
        issues.append(
            f"Expected rule ID '{expected_rule_id}' not found in note text."
        )

    for level in ALL_URGENCY_LEVELS:
        if level != expected_urgency and level in note_upper:
            issues.append(
                f"Incorrect urgency level '{level}' appears in note (expected '{expected_urgency}')."
            )
            break

    return len(issues) == 0, issues

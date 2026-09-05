import os
import json
import logging
import asyncio

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.5-flash-lite"
TEMPERATURE = 0.05


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def _format_fields(condition: dict, fields: dict) -> str:
    all_field_defs = condition["required_fields"] + condition["red_flag_fields"]
    lines = []
    for fd in all_field_defs:
        fname = fd["name"]
        entry = fields.get(fname, {})
        value = entry.get("value")
        confidence = entry.get("confidence", 0.0)
        if value is not None:
            lines.append(f"  {fname}: {value} (confidence: {confidence:.2f})")
        else:
            lines.append(f"  {fname}: NOT COLLECTED")
    return "\n".join(lines)


def _generate_sync(condition: dict, matched_rule: dict, fields: dict) -> str:
    fields_text = _format_fields(condition, fields)
    not_collected = [
        fd["name"]
        for fd in (condition["required_fields"] + condition["red_flag_fields"])
        if fields.get(fd["name"], {}).get("value") is None
    ]
    not_collected_text = ", ".join(not_collected) if not_collected else "none"

    prompt = f"""Write a formal medical triage note using ONLY the verified information below. Do not add diagnoses, assumptions, or information not present in the fields.

Applied Rule ID: {matched_rule['rule_id']}
Rule Text: {matched_rule['rule_text']}
Urgency: {matched_rule['urgency']}
Department: {matched_rule['department']}

Verified Patient Fields:
{fields_text}

Fields not collected: {not_collected_text}

The note MUST:
1. State urgency as exactly "{matched_rule['urgency']}" and department as exactly "{matched_rule['department']}".
2. List what the patient reported based on the verified fields only.
3. Cite the applied rule: "{matched_rule['rule_text']}"
4. Note any fields that were not collected.
5. End with: "Rule ID: {matched_rule['rule_id']}"

Return ONLY valid JSON, no extra text:
{{"note": "<full triage note text>"}}"""
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=TEMPERATURE,
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text.strip())
        return parsed.get("note", "")
    except Exception as e:
        logger.error("Note generation failed: %s", e)
        urgency = matched_rule["urgency"]
        department = matched_rule["department"]
        rule_id = matched_rule["rule_id"]
        rule_text = matched_rule["rule_text"]
        return (
            f"TRIAGE NOTE\n"
            f"Urgency: {urgency}\n"
            f"Department: {department}\n"
            f"Applied Rule: {rule_text}\n"
            f"Collected Fields:\n{fields_text}\n"
            f"Fields Not Collected: {not_collected_text}\n"
            f"Rule ID: {rule_id}"
        )


async def generate(condition: dict, matched_rule: dict, fields: dict) -> str:
    return await asyncio.to_thread(_generate_sync, condition, matched_rule, fields)

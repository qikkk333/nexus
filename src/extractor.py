import os
import json
import logging
import asyncio

from google import genai
from google.genai import types

from . import rules as rules_module

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.5-flash-lite"
TEMPERATURE = 0.1


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def _format_conversation(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = "Patient" if m["role"] == "patient" else "TriageGuard"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)


def _build_extraction_prompt(condition_key: str, conversation_text: str) -> str:
    all_fields = rules_module.get_all_fields_for_condition(condition_key)
    field_lines = "\n".join(
        f"  - name: {f['name']}, type: {f['type']}, description: {f['description']}"
        for f in all_fields
    )
    return f"""You are a medical triage field extractor. Extract the listed fields from the patient conversation.

Fields to extract for condition '{condition_key}':
{field_lines}

Patient conversation:
{conversation_text}

Rules:
- Set value to null and confidence to 0.0 if the field is not mentioned or cannot be inferred.
- confidence 1.0 = explicitly stated. 0.85 = clearly implied. 0.65 = somewhat implied. Below 0.6 = uncertain or absent.
- For boolean fields: value must be true, false, or null (never a string).
- For float fields: value must be a number or null. Convert Fahrenheit to Celsius if needed: (F-32)*5/9.
- For string fields: value must be a short descriptive string or null.
- Return ONLY valid JSON, no extra text.

Return exactly this JSON structure:
{{
  "fields": [
    {{"name": "<field_name>", "value": <value_or_null>, "confidence": <0.0_to_1.0>}}
  ]
}}"""


def _extract_sync(condition_key: str, conversation_text: str) -> dict | None:
    try:
        client = _get_client()
        prompt = _build_extraction_prompt(condition_key, conversation_text)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=TEMPERATURE,
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text.strip())
        result = {}
        for entry in parsed.get("fields", []):
            name = entry.get("name")
            if name:
                result[name] = {
                    "value": entry.get("value"),
                    "confidence": float(entry.get("confidence", 0.0)),
                }
        return result
    except EnvironmentError as e:
        logger.error("API key missing: %s", e)
        return None
    except Exception as e:
        logger.error("Extraction failed for condition '%s': %s", condition_key, e)
        return None


async def extract_fields_for_condition(
    condition_key: str, messages: list[dict]
) -> dict | None:
    conversation_text = _format_conversation(messages)
    return await asyncio.to_thread(_extract_sync, condition_key, conversation_text)


async def extract_all(
    relevant_conditions: list[str], messages: list[dict]
) -> dict | None:
    results = {}
    any_failed = False
    for condition_key in relevant_conditions:
        fields = await extract_fields_for_condition(condition_key, messages)
        if fields is None:
            any_failed = True
            results[condition_key] = {}
        else:
            results[condition_key] = fields
    if any_failed and all(len(v) == 0 for v in results.values()):
        return None
    return results

import os
import json
import logging
import asyncio

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.0-flash-lite"
TEMPERATURE = 0.1


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def _format_recent(messages: list[dict], last_n: int = 4) -> str:
    recent = messages[-last_n:] if len(messages) > last_n else messages
    lines = []
    for m in recent:
        role = "Patient" if m["role"] == "patient" else "TriageGuard"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)


def _ask_sync(field: dict, condition_display_name: str, recent_context: str) -> str:
    prompt = f"""You are a medical triage assistant helping collect information about a patient's {condition_display_name}.
Ask the patient ONE focused, empathetic question to gather this specific information:

Field needed: {field['name']}
Description: {field['description']}
Suggested question: {field['ask']}

Recent conversation:
{recent_context}

Guidelines:
- Ask exactly one question.
- Be clear, brief, and empathetic.
- Do not add diagnoses or medical advice.
- Return ONLY valid JSON, no extra text.

Return exactly this JSON structure:
{{"question": "<your single question here>"}}"""
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
        return parsed.get("question", field["ask"])
    except Exception as e:
        logger.error("Follow-up generation failed: %s", e)
        return field["ask"]


async def get_question(issue: dict, condition_display_name: str, messages: list[dict]) -> str:
    field = issue["field"]
    recent_context = _format_recent(messages)
    return await asyncio.to_thread(_ask_sync, field, condition_display_name, recent_context)

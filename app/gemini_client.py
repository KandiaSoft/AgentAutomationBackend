from __future__ import annotations
import json
from google import genai
from google.genai import types
from app.config import settings
from app.models import AgentQuestionnaireOption, QuestionnaireItem
from app.personas import LANGUAGE_NAMES

_QUESTIONNAIRE_SCHEMA = {
    "type": "object",
    "properties": {
        "questionnaire": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "question": {"type": "string"},
                    "response": {"type": "string"},
                },
                "required": ["number", "question", "response"],
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["questionnaire", "reasoning"],
}

_FREETEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["question", "reasoning"],
}


class GeminiClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def answer_questionnaire(
        self,
        system_prompt: str,
        scenario: str,
        conversation_history: list[dict],
        questionnaire: list[AgentQuestionnaireOption],
        language: str = "it",
    ) -> tuple[list[QuestionnaireItem], str]:
        lang_name = LANGUAGE_NAMES.get(language, "Italian")
        q_text = json.dumps(
            [q.model_dump() for q in questionnaire], ensure_ascii=False, indent=2
        )
        history_text = _format_history(conversation_history)
        user_message = (
            f"Requested scenario: {scenario}\n\n"
            f"Conversation history:\n{history_text}\n\n"
            f"The system sent you the following questionnaire:\n{q_text}\n\n"
            f"For EACH question choose the most suitable option from the 'responses' field. "
            f"Copy the chosen option EXACTLY (including numeric prefix) into the 'response' field. "
            f"Do NOT translate the option text — copy it verbatim. "
            f"Use the free-text option only if no option fits. "
            f"Write the 'reasoning' field in {lang_name}."
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[types.Content(role="user", parts=[types.Part(text=user_message)])],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=_QUESTIONNAIRE_SCHEMA,
            ),
        )
        data = json.loads(response.text)
        items = [
            QuestionnaireItem(
                number=item["number"],
                question=item["question"],
                response=item["response"],
            )
            for item in data["questionnaire"]
        ]
        return items, data.get("reasoning", "")

    async def generate_reply(
        self,
        system_prompt: str,
        scenario: str,
        conversation_history: list[dict],
        agent_answer: str,
        language: str = "it",
    ) -> tuple[str, str]:
        lang_name = LANGUAGE_NAMES.get(language, "Italian")
        history_text = _format_history(conversation_history)
        user_message = (
            f"Requested scenario: {scenario}\n\n"
            f"Conversation history:\n{history_text}\n\n"
            f"The system replied:\n{agent_answer}\n\n"
            f"Write a short reply as the client. "
            f"The 'question' field must be in {lang_name}. "
            f"The 'reasoning' field can be in English."
        )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[types.Content(role="user", parts=[types.Part(text=user_message)])],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=_FREETEXT_SCHEMA,
            ),
        )
        data = json.loads(response.text)
        return data["question"], data.get("reasoning", "")

    async def generate_text(self, prompt: str) -> str:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        return response.text.strip()


def _format_history(history: list[dict]) -> str:
    lines = []
    for h in history:
        role = "CLIENT" if h["role"] == "client" else "AGENT"
        text = h.get("question") or h.get("answer") or ""
        lines.append(f"{role}: {text}")
    return "\n".join(lines) if lines else "(none)"


gemini = GeminiClient()

from __future__ import annotations
import json
import logging
from google import genai
from google.genai import types
from app.config import settings
from app.models import AgentQuestionnaireOption, QuestionnaireItem
from app.personas import LANGUAGE_NAMES

logger = logging.getLogger(__name__)

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
                    "expert_code": {"type": "string"},
                },
                "required": ["number", "question", "response", "expert_code"],
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


def _is_placeholder_echo(response: str, options: list[str]) -> bool:
    """
    True when the model copied the last (free-text) option verbatim instead of writing
    a real answer. By convention the last option is always the 'write your own answer'
    placeholder — using it means the model should produce custom text with the same
    numeric prefix, never the literal placeholder.
    """
    if not options:
        return False
    return response.strip() == options[-1].strip()


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
        history_text = _format_history(conversation_history)
        q_text = json.dumps(
            [q.model_dump() for q in questionnaire], ensure_ascii=False, indent=2
        )

        user_message = self._build_questionnaire_prompt(
            scenario=scenario,
            history_text=history_text,
            q_text=q_text,
            lang_name=lang_name,
        )
        data = await self._call_questionnaire(system_prompt, user_message)

        items = [
            QuestionnaireItem(
                number=item["number"],
                question=item["question"],
                response=item["response"],
                expert_code=item.get("expert_code") or None,
            )
            for item in data["questionnaire"]
        ]
        reasoning = data.get("reasoning", "")

        # Detect & repair "placeholder echo" bug: when the model picked the free-text
        # option but just copied its placeholder text instead of writing real content.
        items, reasoning = await self._repair_placeholder_echoes(
            system_prompt=system_prompt,
            scenario=scenario,
            history_text=history_text,
            questionnaire=questionnaire,
            items=items,
            reasoning=reasoning,
            lang_name=lang_name,
        )
        return items, reasoning

    def _build_questionnaire_prompt(
        self,
        scenario: str,
        history_text: str,
        q_text: str,
        lang_name: str,
        repair_note: str = "",
    ) -> str:
        return (
            f"Requested scenario: {scenario}\n\n"
            f"Conversation history:\n{history_text}\n\n"
            f"The system sent you the following questionnaire:\n{q_text}\n\n"
            f"For EACH question, look at the 'responses' array and either:\n"
            f"  (A) PICK one of the predefined options that matches the scenario, and copy its text "
            f"EXACTLY (including the numeric prefix) into the 'response' field, OR\n"
            f"  (B) USE THE FREE-TEXT OPTION (always the LAST item in 'responses', e.g. "
            f"'4. Scrivi la tua risposta', '3. Write your answer', '5. Escribe tu respuesta'). "
            f"This option is a PLACEHOLDER. If you choose it, you MUST replace its placeholder text "
            f"with your real custom answer, keeping ONLY the numeric prefix.\n\n"
            f"CRITICAL — examples for option (B):\n"
            f"  Wrong: '4. Scrivi la tua risposta'   ← never echo the placeholder text\n"
            f"  Wrong: '4. La tua risposta'           ← still placeholder\n"
            f"  Right: '4. La mia parete è in cartongesso, ho un'opzione alternativa?'\n"
            f"  Right: '4. Non sono sicuro, puoi spiegarmi la differenza tra i due materiali?'\n"
            f"  Right: '4. Preferirei una marca specifica: Knauf.'\n\n"
            f"The free-text answer can be: a counter-question, a clarification request, "
            f"a doubt, a recommendation, or any answer not covered by the predefined options. "
            f"It MUST be written in {lang_name}, must be meaningful in the scenario context, "
            f"and must NEVER be the placeholder text itself.\n\n"
            f"Other rules:\n"
            f"- Do NOT translate the predefined options when you pick them — copy them verbatim.\n"
            f"- Copy 'number' AND 'expert_code' EXACTLY as received. The pair (expert_code, number) "
            f"is the unique key per question.\n"
            f"- If 'expert_code' was missing or null, return an empty string \"\" for it.\n"
            f"- Write the 'reasoning' field in {lang_name}.\n"
            f"{repair_note}"
        )

    async def _call_questionnaire(self, system_prompt: str, user_message: str) -> dict:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[types.Content(role="user", parts=[types.Part(text=user_message)])],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=_QUESTIONNAIRE_SCHEMA,
            ),
        )
        return json.loads(response.text)

    async def _repair_placeholder_echoes(
        self,
        system_prompt: str,
        scenario: str,
        history_text: str,
        questionnaire: list[AgentQuestionnaireOption],
        items: list[QuestionnaireItem],
        reasoning: str,
        lang_name: str,
        max_retries: int = 2,
    ) -> tuple[list[QuestionnaireItem], str]:
        """Detect items where the model echoed the free-text placeholder and re-ask
        for a real answer on those items only. Up to `max_retries` repair rounds."""
        # Index originals by composite key
        originals = {(q.expert_code, q.number): q for q in questionnaire}

        for attempt in range(max_retries):
            bad_keys = [
                (it.expert_code, it.number)
                for it in items
                if (it.expert_code, it.number) in originals
                and _is_placeholder_echo(
                    it.response, originals[(it.expert_code, it.number)].responses
                )
            ]
            if not bad_keys:
                return items, reasoning

            logger.warning(
                "Placeholder echo detected on %d question(s) — repair attempt %d/%d: %s",
                len(bad_keys),
                attempt + 1,
                max_retries,
                bad_keys,
            )

            bad_originals = [originals[k] for k in bad_keys]
            q_text = json.dumps(
                [q.model_dump() for q in bad_originals], ensure_ascii=False, indent=2
            )
            repair_note = (
                "\nIMPORTANT: this is a REPAIR round. The previous attempt copied the "
                "free-text placeholder verbatim for these questions. You MUST now produce "
                "a real, meaningful custom answer for each one, keeping the numeric prefix "
                "of the placeholder but replacing its text. Do not echo the placeholder again."
            )
            user_message = self._build_questionnaire_prompt(
                scenario=scenario,
                history_text=history_text,
                q_text=q_text,
                lang_name=lang_name,
                repair_note=repair_note,
            )

            try:
                data = await self._call_questionnaire(system_prompt, user_message)
            except Exception as exc:
                logger.error("Repair round failed: %s — keeping previous responses", exc)
                return items, reasoning

            # Merge repaired items back into the full list
            repaired = {
                (it.get("expert_code") or None, it["number"]): it
                for it in data["questionnaire"]
            }
            items = [
                (
                    QuestionnaireItem(
                        number=it.number,
                        question=it.question,
                        response=repaired[(it.expert_code, it.number)]["response"],
                        expert_code=it.expert_code,
                    )
                    if (it.expert_code, it.number) in repaired
                    else it
                )
                for it in items
            ]
            if data.get("reasoning"):
                reasoning = f"{reasoning}\n[repair {attempt + 1}] {data['reasoning']}"

        return items, reasoning

    async def generate_reply(
        self,
        system_prompt: str,
        scenario: str,
        conversation_history: list[dict],
        agent_answer: str,
        language: str = "it",
        extra_instruction: str | None = None,
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
        if extra_instruction:
            user_message += f"\n\n{extra_instruction}"
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

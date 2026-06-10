from __future__ import annotations
import asyncio
import json
import logging
import httpx
from app.config import settings
from app.models import AgentRequest, AgentResponse, QuestionnaireItem

logger = logging.getLogger(__name__)


class PreventivatoreClient:
    def __init__(self) -> None:
        # verify=False only makes sense for HTTPS (self-signed certs on test servers).
        # For plain HTTP (e.g. localhost) it is irrelevant but harmless; the important
        # thing is that the URL scheme matches what the server actually speaks.
        is_https = settings.effective_agent_url.startswith("https://")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.agent_timeout_connect,
                read=settings.agent_timeout_read,
                write=10.0,
                pool=10.0,
            ),
            verify=False if is_https else True,
        )

    async def invoke(
        self,
        thread_id: str,
        question: str,
        interrupt: int,
        questionnaire: list[QuestionnaireItem],
    ) -> AgentResponse:
        payload = AgentRequest(
            user_id=settings.agent_user_id,
            thread_id=thread_id,
            question=question,
            username=settings.agent_username,
            interrupt=interrupt,
            questionnaire=questionnaire,
        )
        body = payload.model_dump(exclude_none=True)

        logger.info(
            "→ POST %s  thread=%s  interrupt=%d  q_items=%d",
            settings.effective_agent_url,
            thread_id,
            interrupt,
            len(questionnaire),
        )
        logger.debug("  request body:\n%s", json.dumps(body, ensure_ascii=False, indent=2))

        for attempt in range(settings.agent_max_retries + 1):
            try:
                response = await self._client.post(settings.effective_agent_url, json=body)
                if not response.is_success:
                    logger.error(
                        "← %d %s  thread=%s\n%s",
                        response.status_code,
                        response.reason_phrase,
                        thread_id,
                        response.text,
                    )
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} {response.reason_phrase}: {response.text}",
                        request=response.request,
                        response=response,
                    )

                raw = response.json()
                agent_resp = AgentResponse.model_validate(raw)

                tokens_raw = raw.get("tokens", [])
                total_in = sum(t.in_tokens for t in agent_resp.tokens)
                total_out = sum(t.out_tokens for t in agent_resp.tokens)
                logger.info(
                    "← 200  thread=%s  finished=%s  is_questionnaire=%s  agent=%s  q_items=%d  tokens=↑%d ↓%d (entries=%d)",
                    thread_id,
                    agent_resp.finished,
                    agent_resp.is_questionnaire,
                    agent_resp.agent,
                    len(agent_resp.questionnaire),
                    total_in,
                    total_out,
                    len(tokens_raw),
                )
                logger.info(
                    "  tokens payload from agent:\n%s",
                    json.dumps(tokens_raw, ensure_ascii=False, indent=2),
                )
                logger.debug("  response body:\n%s", json.dumps(raw, ensure_ascii=False, indent=2))
                return agent_resp

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                logger.warning(
                    "  timeout on attempt %d/%d for thread=%s: %s",
                    attempt + 1,
                    settings.agent_max_retries + 1,
                    thread_id,
                    exc,
                )
                if attempt >= settings.agent_max_retries:
                    raise
                wait = 5.0 * (attempt + 1)
                await asyncio.sleep(wait)

    async def close(self) -> None:
        await self._client.aclose()


agent_client = PreventivatoreClient()

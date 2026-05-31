from __future__ import annotations
import asyncio
import httpx
from app.config import settings
from app.models import AgentRequest, AgentResponse, QuestionnaireItem


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

        for attempt in range(settings.agent_max_retries + 1):
            try:
                response = await self._client.post(settings.effective_agent_url, json=body)
                if not response.is_success:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} {response.reason_phrase}: {response.text}",
                        request=response.request,
                        response=response,
                    )
                return AgentResponse.model_validate(response.json())
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                if attempt >= settings.agent_max_retries:
                    raise
                wait = 5.0 * (attempt + 1)  # 5s first retry, 10s second
                await asyncio.sleep(wait)

    async def close(self) -> None:
        await self._client.aclose()


agent_client = PreventivatoreClient()

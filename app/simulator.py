from __future__ import annotations
import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from app.agent_client import agent_client
from app.config import settings
from app.db import insert_turn, update_simulation
from app.gemini_client import gemini
from app.models import AgentQuestionnaireOption, QuestionnaireItem, SimulationConfig
from app.personas import get_system_prompt
from app.scenarios import SCENARIOS, generate_random_scenario


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_delay(min_ms: int, max_ms: int) -> float:
    import random
    return random.randint(min_ms, max_ms) / 1000.0


class ClientSimulator:
    def __init__(self, sim_id: str, thread_id: str, config: SimulationConfig, broadcast) -> None:
        self.sim_id = sim_id
        self.thread_id = thread_id
        self.config = config
        self._broadcast = broadcast
        self._history: list[dict] = []
        self._turn_index = 0
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0

    async def run(self) -> None:
        try:
            await update_simulation(self.sim_id, status="running")
            await self._broadcast(self.sim_id, "status", {"status": "running"})

            scenario = await self._resolve_scenario()
            system_prompt = get_system_prompt(self.config.persona_key, self.config.language)

            # Turn 1: client sends initial request
            await self._client_turn(
                question=scenario,
                questionnaire=[],
                interrupt=0,
                reasoning="Initial scenario request",
                system_prompt=system_prompt,
                record_as_client=True,
            )

            # Main loop
            while True:
                _t0 = time.monotonic()
                agent_resp = await agent_client.invoke(
                    thread_id=self.thread_id,
                    question=self._history[-1].get("question", ""),
                    interrupt=self._history[-1].get("interrupt", 0),
                    questionnaire=self._history[-1].get("questionnaire_items", []),
                )
                duration_ms = int((time.monotonic() - _t0) * 1000)

                in_tok = sum(t.in_tokens for t in agent_resp.tokens)
                out_tok = sum(t.out_tokens for t in agent_resp.tokens)
                self._total_in += in_tok
                self._total_out += out_tok

                # tokens_cost.total_cost is the CUMULATIVE cost of the whole chat,
                # so we take the latest reported value (overwrite, not sum).
                if agent_resp.tokens_cost:
                    cost = agent_resp.tokens_cost.get("total_cost")
                    if isinstance(cost, (int, float)):
                        self._total_cost = float(cost)

                agent_entry = {
                    "role": "agent",
                    "answer": agent_resp.answer,
                    "understanding": agent_resp.understanding,
                    "is_questionnaire": agent_resp.is_questionnaire,
                    "has_interrupt": agent_resp.has_interrupt,
                    "questionnaire": [q.model_dump() for q in agent_resp.questionnaire],
                    "finished": agent_resp.finished,
                }
                self._history.append(agent_entry)

                turn_id = await insert_turn({
                    "simulation_id": self.sim_id,
                    "turn_index": self._turn_index,
                    "role": "agent",
                    "question": None,
                    "answer": agent_resp.answer,
                    "understanding": agent_resp.understanding,
                    "is_questionnaire": int(agent_resp.is_questionnaire),
                    "has_interrupt": int(agent_resp.has_interrupt),
                    "questionnaire_json": json.dumps(
                        [q.model_dump() for q in agent_resp.questionnaire], ensure_ascii=False
                    ),
                    "client_reasoning": None,
                    "in_tokens": in_tok,
                    "out_tokens": out_tok,
                    "duration_ms": duration_ms,
                    "created_at": _now(),
                })
                self._turn_index += 1
                await update_simulation(
                    self.sim_id,
                    total_in_tokens=self._total_in,
                    total_out_tokens=self._total_out,
                    total_cost=self._total_cost,
                )
                await self._broadcast(self.sim_id, "turn", {
                    "turn_index": self._turn_index - 1,
                    "role": "agent",
                    "answer": agent_resp.answer,
                    "understanding": agent_resp.understanding,
                    "is_questionnaire": agent_resp.is_questionnaire,
                    "has_interrupt": agent_resp.has_interrupt,
                    "questionnaire": [q.model_dump() for q in agent_resp.questionnaire],
                    "in_tokens": in_tok,
                    "out_tokens": out_tok,
                    "duration_ms": duration_ms,
                    "total_cost": self._total_cost,
                })

                if agent_resp.finished:
                    await update_simulation(
                        self.sim_id,
                        status="finished",
                        finished=1,
                        short_codes_json=json.dumps(agent_resp.short_codes, ensure_ascii=False),
                        finished_at=_now(),
                    )
                    await self._broadcast(self.sim_id, "status", {
                        "status": "finished",
                        "short_codes": agent_resp.short_codes,
                    })
                    return

                # Delay before client responds
                delay = _random_delay(self.config.delay_ms[0], self.config.delay_ms[1])
                await asyncio.sleep(delay)

                # Build client reply
                interrupt = 1 if agent_resp.has_interrupt else 0
                if agent_resp.is_questionnaire:
                    q_options = [AgentQuestionnaireOption(**q.model_dump()) for q in agent_resp.questionnaire]
                    q_items, reasoning = await gemini.answer_questionnaire(
                        system_prompt=system_prompt,
                        scenario=scenario,
                        conversation_history=self._history,
                        questionnaire=q_options,
                        language=self.config.language,
                    )
                    await self._client_turn(
                        question="",
                        questionnaire=q_items,
                        interrupt=interrupt,
                        reasoning=reasoning,
                        system_prompt=system_prompt,
                        record_as_client=True,
                    )
                else:
                    reply, reasoning = await gemini.generate_reply(
                        system_prompt=system_prompt,
                        scenario=scenario,
                        conversation_history=self._history,
                        agent_answer=agent_resp.answer,
                        language=self.config.language,
                    )
                    await self._client_turn(
                        question=reply,
                        questionnaire=[],
                        interrupt=interrupt,
                        reasoning=reasoning,
                        system_prompt=system_prompt,
                        record_as_client=True,
                    )

        except asyncio.CancelledError:
            await update_simulation(self.sim_id, status="stopped", finished_at=_now())
            await self._broadcast(self.sim_id, "status", {"status": "stopped"})
        except Exception as exc:
            error_msg = str(exc)
            await update_simulation(self.sim_id, status="error", error=error_msg, finished_at=_now())
            await self._broadcast(self.sim_id, "status", {"status": "error", "error": error_msg})
            raise

    async def _resolve_scenario(self) -> str:
        if self.config.scenario_text:
            return self.config.scenario_text
        if self.config.generate_scenario:
            return await generate_random_scenario(self.config.persona_key, self.config.language)
        if self.config.scenario_key:
            s = SCENARIOS.get(self.config.scenario_key)
            if s:
                return s["text"]
        raise ValueError("No scenario provided")

    async def _client_turn(
        self,
        question: str,
        questionnaire: list[QuestionnaireItem],
        interrupt: int,
        reasoning: str,
        system_prompt: str,
        record_as_client: bool,
    ) -> None:
        entry = {
            "role": "client",
            "question": question,
            "questionnaire_items": questionnaire,
            "interrupt": interrupt,
        }
        self._history.append(entry)

        q_display = [item.model_dump() for item in questionnaire]
        await insert_turn({
            "simulation_id": self.sim_id,
            "turn_index": self._turn_index,
            "role": "client",
            "question": question,
            "answer": None,
            "understanding": None,
            "is_questionnaire": int(bool(questionnaire)),
            "has_interrupt": interrupt,
            "questionnaire_json": json.dumps(q_display, ensure_ascii=False),
            "client_reasoning": reasoning,
            "in_tokens": 0,
            "out_tokens": 0,
            "duration_ms": None,
            "created_at": _now(),
        })
        self._turn_index += 1
        await self._broadcast(self.sim_id, "turn", {
            "turn_index": self._turn_index - 1,
            "role": "client",
            "question": question,
            "questionnaire": q_display,
            "client_reasoning": reasoning,
            "interrupt": interrupt,
        })

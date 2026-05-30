"""Tests for ClientSimulator with mocked agent and Gemini."""
import pytest
from unittest.mock import AsyncMock, patch
from app.models import (
    AgentQuestionnaireOption,
    AgentResponse,
    QuestionnaireItem,
    SimulationConfig,
    TokenUsage,
)


@pytest.fixture
def basic_config() -> SimulationConfig:
    return SimulationConfig(
        persona_key="homeowner_basic",
        scenario_text="Devo sostituire un interruttore in bagno.",
        count=1,
        delay_ms=[0, 0],
    )


def make_agent_response(
    answer: str,
    finished: bool = False,
    is_questionnaire: bool = False,
    has_interrupt: bool = False,
    questionnaire: list | None = None,
    short_codes: list | None = None,
) -> AgentResponse:
    return AgentResponse(
        answer=answer,
        tokens=[TokenUsage(in_tokens=10, out_tokens=5, model="gemini")],
        understanding="test understanding",
        has_interrupt=has_interrupt,
        status="success",
        short_codes=short_codes or [],
        finished=finished,
        questionnaire=[
            AgentQuestionnaireOption(**q) for q in (questionnaire or [])
        ],
        is_questionnaire=is_questionnaire,
    )


@pytest.mark.asyncio
async def test_simulator_completes_simple_flow(basic_config):
    """Simulator should finish after agent returns finished=True."""
    sim_id = "test-sim-id"
    thread_id = "test-thread-id"
    events = []

    async def broadcast(sid, etype, payload):
        events.append((etype, payload))

    # Agent: first response is a plain answer, second is finished
    agent_responses = [
        make_agent_response("Grazie, ho capito la tua richiesta.", finished=False),
        make_agent_response("Preventivo pronto!", finished=True, short_codes=["ELEC001"]),
    ]
    call_count = 0

    async def mock_invoke(**kwargs):
        nonlocal call_count
        resp = agent_responses[call_count]
        call_count += 1
        return resp

    async def mock_generate_reply(**kwargs):
        return "Ok, confermo.", "Client confirmed"

    with patch("app.simulator.agent_client") as mock_agent, \
         patch("app.simulator.gemini") as mock_gemini, \
         patch("app.simulator.insert_turn", new_callable=AsyncMock) as mock_insert, \
         patch("app.simulator.update_simulation", new_callable=AsyncMock):

        mock_agent.invoke = AsyncMock(side_effect=mock_invoke)
        mock_gemini.generate_reply = AsyncMock(side_effect=mock_generate_reply)
        mock_insert.return_value = 1

        from app.simulator import ClientSimulator
        sim = ClientSimulator(sim_id, thread_id, basic_config, broadcast)
        await sim.run()

    assert any(e[0] == "status" and e[1].get("status") == "finished" for e in events)
    assert call_count == 2


@pytest.mark.asyncio
async def test_simulator_handles_questionnaire(basic_config):
    """Simulator should call gemini.answer_questionnaire when agent sends questionnaire."""
    sim_id = "test-sim-id-q"
    thread_id = "test-thread-id-q"
    questionnaire_used = []

    async def broadcast(sid, etype, payload):
        pass

    q_options = [
        {
            "number": 1,
            "question": "Tipo di sostituzione?",
            "responses": [
                "1. Semplice sostituzione frutti",
                "2. Modifica cablaggi",
                "3. Rifacimento completo",
                "4. Scrivi la tua risposta",
            ],
        }
    ]
    agent_responses = [
        make_agent_response(
            "Ho bisogno di alcune informazioni.",
            is_questionnaire=True,
            has_interrupt=True,
            questionnaire=q_options,
        ),
        make_agent_response("Preventivo completato!", finished=True, short_codes=["ELEC002"]),
    ]
    call_count = 0

    async def mock_invoke(**kwargs):
        nonlocal call_count
        resp = agent_responses[call_count]
        call_count += 1
        return resp

    async def mock_answer_questionnaire(**kwargs):
        q = kwargs.get("questionnaire", [])
        questionnaire_used.extend(q)
        items = [QuestionnaireItem(number=1, question="Tipo?", response="1. Semplice sostituzione frutti")]
        return items, "Chose option 1 as most relevant"

    with patch("app.simulator.agent_client") as mock_agent, \
         patch("app.simulator.gemini") as mock_gemini, \
         patch("app.simulator.insert_turn", new_callable=AsyncMock) as mock_insert, \
         patch("app.simulator.update_simulation", new_callable=AsyncMock):

        mock_agent.invoke = AsyncMock(side_effect=mock_invoke)
        mock_gemini.answer_questionnaire = AsyncMock(side_effect=mock_answer_questionnaire)
        mock_insert.return_value = 1

        from app.simulator import ClientSimulator
        sim = ClientSimulator(sim_id, thread_id, basic_config, broadcast)
        await sim.run()

    assert len(questionnaire_used) == 1
    assert call_count == 2


@pytest.mark.asyncio
async def test_simulator_error_handling(basic_config):
    """Simulator should mark status=error on exception."""
    sim_id = "test-error-sim"
    thread_id = "test-thread-id-err"
    status_events = []

    async def broadcast(sid, etype, payload):
        if etype == "status":
            status_events.append(payload)

    with patch("app.simulator.agent_client") as mock_agent, \
         patch("app.simulator.insert_turn", new_callable=AsyncMock), \
         patch("app.simulator.update_simulation", new_callable=AsyncMock):

        mock_agent.invoke = AsyncMock(side_effect=Exception("Connection refused"))

        from app.simulator import ClientSimulator
        sim = ClientSimulator(sim_id, thread_id, basic_config, broadcast)
        with pytest.raises(Exception, match="Connection refused"):
            await sim.run()

    assert any(e.get("status") == "error" for e in status_events)

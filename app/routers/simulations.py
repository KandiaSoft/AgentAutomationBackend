from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException, Query
from app.db import get_simulation, get_turns, list_simulations, update_simulation
from app.manager import manager
from app.models import (
    SimulationConfig,
    SimulationDetail,
    SimulationSummary,
    StartResponse,
    TurnRecord,
)

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


def _row_to_summary(row: dict) -> SimulationSummary:
    return SimulationSummary(
        id=row["id"],
        thread_id=row["thread_id"],
        persona_key=row["persona_key"],
        scenario_key=row.get("scenario_key"),
        initial_request=row["initial_request"],
        language=row.get("language", "it"),
        status=row["status"],
        finished=bool(row["finished"]),
        total_in_tokens=row["total_in_tokens"],
        total_out_tokens=row["total_out_tokens"],
        turn_count=row.get("turn_count", 0),
        created_at=row["created_at"],
        finished_at=row.get("finished_at"),
        error=row.get("error"),
        short_codes=json.loads(row.get("short_codes_json") or "[]"),
    )


def _row_to_turn(row: dict) -> TurnRecord:
    return TurnRecord(
        id=row["id"],
        simulation_id=row["simulation_id"],
        turn_index=row["turn_index"],
        role=row["role"],
        question=row.get("question"),
        answer=row.get("answer"),
        understanding=row.get("understanding"),
        is_questionnaire=bool(row["is_questionnaire"]),
        has_interrupt=bool(row["has_interrupt"]),
        questionnaire=json.loads(row.get("questionnaire_json") or "[]"),
        client_reasoning=row.get("client_reasoning"),
        in_tokens=row["in_tokens"],
        out_tokens=row["out_tokens"],
        created_at=row["created_at"],
    )


@router.post("", response_model=StartResponse)
async def start_simulations(config: SimulationConfig):
    if not config.scenario_key and not config.scenario_text and not config.generate_scenario:
        raise HTTPException(400, "Provide scenario_key, scenario_text or generate_scenario=true")
    ids = await manager.start_batch(config)
    return StartResponse(simulation_ids=ids)


@router.get("", response_model=list[SimulationSummary])
async def list_sims(status: str | None = Query(None)):
    rows = await list_simulations(status)
    return [_row_to_summary(r) for r in rows]


@router.get("/{sim_id}", response_model=SimulationDetail)
async def get_sim(sim_id: str):
    row = await get_simulation(sim_id)
    if not row:
        raise HTTPException(404, "Simulation not found")
    turns_rows = await get_turns(sim_id)
    summary = _row_to_summary({**row, "turn_count": len(turns_rows)})
    turns = [_row_to_turn(t) for t in turns_rows]
    return SimulationDetail(**summary.model_dump(), turns=turns)


@router.delete("/{sim_id}", status_code=204)
async def stop_sim(sim_id: str):
    row = await get_simulation(sim_id)
    if not row:
        raise HTTPException(404, "Simulation not found")
    manager.stop_simulation(sim_id)

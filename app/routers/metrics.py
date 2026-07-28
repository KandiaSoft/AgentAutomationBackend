from __future__ import annotations
from fastapi import APIRouter
from app.token_meter import token_meter

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/tpm")
async def get_tpm() -> dict:
    """Aggregate tokens-per-minute across all running simulations (sliding 60s
    window). `input_tpm` counts input tokens including cached ones — the metric
    that Gemini's per-minute quota measures."""
    return token_meter.stats()

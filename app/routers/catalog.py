from fastapi import APIRouter
from app.models import Persona, Scenario
from app.personas import get_persona_list
from app.scenarios import get_scenario_list

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/personas", response_model=list[Persona])
async def list_personas():
    return get_persona_list()


@router.get("/scenarios", response_model=list[Scenario])
async def list_scenarios():
    return get_scenario_list()

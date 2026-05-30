from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db import init_db
from app.agent_client import agent_client
from app.routers import simulations, catalog, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await agent_client.close()


app = FastAPI(title="AgentAutomaton", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simulations.router)
app.include_router(catalog.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

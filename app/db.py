from __future__ import annotations
import aiosqlite
from app.config import settings

_CREATE_SIMULATIONS = """
CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    persona_key TEXT NOT NULL,
    scenario_key TEXT,
    initial_request TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'it',
    status TEXT NOT NULL DEFAULT 'pending',
    finished INTEGER NOT NULL DEFAULT 0,
    short_codes_json TEXT NOT NULL DEFAULT '[]',
    total_in_tokens INTEGER NOT NULL DEFAULT 0,
    total_out_tokens INTEGER NOT NULL DEFAULT 0,
    delay_min_ms INTEGER NOT NULL DEFAULT 2000,
    delay_max_ms INTEGER NOT NULL DEFAULT 6000,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);
"""

_CREATE_TURNS = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    understanding TEXT,
    is_questionnaire INTEGER NOT NULL DEFAULT 0,
    has_interrupt INTEGER NOT NULL DEFAULT 0,
    questionnaire_json TEXT NOT NULL DEFAULT '[]',
    client_reasoning TEXT,
    in_tokens INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(_CREATE_SIMULATIONS)
        await db.execute(_CREATE_TURNS)
        # Migration: add language column to existing DBs
        try:
            await db.execute("ALTER TABLE simulations ADD COLUMN language TEXT NOT NULL DEFAULT 'it'")
        except Exception:
            pass  # column already exists
        await db.commit()


async def insert_simulation(sim: dict) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """INSERT INTO simulations (id, thread_id, persona_key, scenario_key, initial_request,
               language, status, delay_min_ms, delay_max_ms, created_at)
               VALUES (:id, :thread_id, :persona_key, :scenario_key, :initial_request,
               :language, :status, :delay_min_ms, :delay_max_ms, :created_at)""",
            sim,
        )
        await db.commit()


async def update_simulation(sim_id: str, **fields) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["sim_id"] = sim_id
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(f"UPDATE simulations SET {set_clause} WHERE id = :sim_id", fields)
        await db.commit()


async def insert_turn(turn: dict) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            """INSERT INTO turns (simulation_id, turn_index, role, question, answer, understanding,
               is_questionnaire, has_interrupt, questionnaire_json, client_reasoning,
               in_tokens, out_tokens, created_at)
               VALUES (:simulation_id, :turn_index, :role, :question, :answer, :understanding,
               :is_questionnaire, :has_interrupt, :questionnaire_json, :client_reasoning,
               :in_tokens, :out_tokens, :created_at)""",
            turn,
        )
        await db.commit()
        return cursor.lastrowid


async def get_simulation(sim_id: str) -> dict | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM simulations WHERE id = ?", (sim_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_turns(sim_id: str) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM turns WHERE simulation_id = ? ORDER BY turn_index, id", (sim_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def list_simulations(status: str | None = None) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        if status:
            query = """
                SELECT s.*, (SELECT COUNT(*) FROM turns t WHERE t.simulation_id = s.id) AS turn_count
                FROM simulations s WHERE s.status = ? ORDER BY s.created_at DESC
            """
            async with db.execute(query, (status,)) as cur:
                rows = await cur.fetchall()
        else:
            query = """
                SELECT s.*, (SELECT COUNT(*) FROM turns t WHERE t.simulation_id = s.id) AS turn_count
                FROM simulations s ORDER BY s.created_at DESC
            """
            async with db.execute(query) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

from __future__ import annotations
import asyncio
import json
import uuid
from app.config import settings
from app.db import insert_simulation
from app.models import SimulationConfig
from app.simulator import ClientSimulator, _now


class SimulationManager:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.max_concurrent)
        self._active: dict[str, asyncio.Task] = {}
        # WS subscribers: sim_id -> list of queues; None key = global subscriber
        self._subscribers: dict[str | None, list[asyncio.Queue]] = {}

    def subscribe(self, sim_id: str | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(sim_id, []).append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, sim_id: str | None = None) -> None:
        subs = self._subscribers.get(sim_id, [])
        if q in subs:
            subs.remove(q)

    async def _broadcast(self, sim_id: str, event_type: str, payload: dict) -> None:
        msg = json.dumps({"type": event_type, "simulation_id": sim_id, "payload": payload})
        for q in list(self._subscribers.get(sim_id, [])):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
        for q in list(self._subscribers.get(None, [])):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def start_simulation(self, config: SimulationConfig, startup_delay: float = 0.0) -> str:
        sim_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        await insert_simulation({
            "id": sim_id,
            "thread_id": thread_id,
            "persona_key": config.persona_key,
            "scenario_key": config.scenario_key,
            "initial_request": config.scenario_text or config.scenario_key or "generated",
            "language": config.language,
            "status": "pending",
            "delay_min_ms": config.delay_ms[0],
            "delay_max_ms": config.delay_ms[1],
            "created_at": _now(),
        })
        sim = ClientSimulator(sim_id, thread_id, config, self._broadcast)
        task = asyncio.create_task(self._run_with_semaphore(sim, startup_delay))
        self._active[sim_id] = task
        task.add_done_callback(lambda _: self._active.pop(sim_id, None))
        return sim_id

    async def _run_with_semaphore(self, sim: ClientSimulator, startup_delay: float = 0.0) -> None:
        # Stagger the start of each simulation in a batch. Done before acquiring the
        # semaphore so the spacing is real regardless of the concurrency limit.
        if startup_delay > 0:
            await asyncio.sleep(startup_delay)
        async with self._semaphore:
            try:
                await sim.run()
            except Exception:
                # sim.run() already persisted the error to DB and broadcast it;
                # suppress here to avoid "Task exception was never retrieved" noise.
                pass

    async def start_batch(self, config: SimulationConfig) -> list[str]:
        stagger = config.stagger_ms / 1000.0
        ids = []
        for i in range(config.count):
            # First launches immediately; each subsequent one waits i * stagger.
            sid = await self.start_simulation(config, startup_delay=i * stagger)
            ids.append(sid)
        return ids

    def stop_simulation(self, sim_id: str) -> bool:
        task = self._active.get(sim_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def is_active(self, sim_id: str) -> bool:
        task = self._active.get(sim_id)
        return bool(task and not task.done())


manager = SimulationManager()

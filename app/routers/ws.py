from __future__ import annotations
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/simulations")
async def ws_all(websocket: WebSocket):
    """Stream events for ALL simulations."""
    await websocket.accept()
    q = manager.subscribe(sim_id=None)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(q, sim_id=None)


@router.websocket("/ws/simulations/{sim_id}")
async def ws_one(websocket: WebSocket, sim_id: str):
    """Stream events for a single simulation."""
    await websocket.accept()
    q = manager.subscribe(sim_id=sim_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(q, sim_id=sim_id)

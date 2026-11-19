import asyncio
import logging

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError

from manura.container import Container
from manura.domain.models import (
    ClientControl,
    ErrorMessage,
    ServerMessage,
    StartedMessage,
    StoppedMessage,
)
from manura.services.recording import TurnRecording

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/audio")
async def ws_audio(ws: WebSocket) -> None:
    container: Container = ws.app.state.container
    await ws.accept()
    send_lock = asyncio.Lock()

    async def emit(message: ServerMessage) -> None:
        async with send_lock:
            await ws.send_text(message.model_dump_json())

    turn: TurnRecording | None = None
    try:
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if (data := frame.get("bytes")) is not None:
                if turn is not None:
                    turn.feed(data)
                continue
            text = frame.get("text")
            if text is None:
                continue
            try:
                control = ClientControl.model_validate_json(text)
            except ValidationError:
                await emit(ErrorMessage(code="BAD_MESSAGE", message="알 수 없는 제어 메시지"))
                continue
            if control.type == "start":
                if turn is not None:
                    await emit(ErrorMessage(code="ALREADY_RECORDING", message="이미 녹음 중입니다"))
                    continue
                turn = await container.recording.new_turn(emit)
                await emit(StartedMessage(turn_id=turn.turn_id))
                turn.begin()
            elif turn is not None:
                await turn.stop()
                await emit(StoppedMessage(turn_id=turn.turn_id))
                turn = None
    finally:
        if turn is not None:
            await turn.abort()

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from manura.domain.errors import STTError
from manura.domain.models import (
    ErrorMessage,
    FinalMessage,
    PartialMessage,
    ServerMessage,
    TranscriptEvent,
)
from manura.domain.ports import STTEngine, TranscriptStore

log = logging.getLogger(__name__)

Emit = Callable[[ServerMessage], Awaitable[None]]


def _to_message(event: TranscriptEvent) -> ServerMessage:
    if event.kind == "partial":
        return PartialMessage(text=event.text)
    return FinalMessage(text=event.text, start_ms=event.start_ms, end_ms=event.end_ms)


class TurnRecording:
    """한 번의 녹음 구간(start~stop). 오디오를 STT에 흘려보내고 결과를 emit한다."""

    def __init__(
        self,
        turn_id: str,
        stt: STTEngine,
        store: TranscriptStore,
        emit: Emit,
        finalize_timeout_s: float,
    ) -> None:
        self.turn_id = turn_id
        self._stt = stt
        self._store = store
        self._emit = emit
        self._finalize_timeout_s = finalize_timeout_s
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._input_closed = False
        self._task: asyncio.Task[None] | None = None
        self._audio_bytes = 0

    def begin(self) -> None:
        self._task = asyncio.create_task(self._run())

    def feed(self, chunk: bytes) -> None:
        if not self._input_closed:
            self._audio_bytes += len(chunk)
            self._queue.put_nowait(chunk)

    async def stop(self) -> None:
        """입력을 닫고 최종 결과를 기다린다. 상한을 넘기면 받은 데까지만 확정한다."""
        self._close_input()
        if self._task is None:
            return
        done, _ = await asyncio.wait({self._task}, timeout=self._finalize_timeout_s)
        if not done:
            log.warning("turn %s: finalize timeout, 받은 결과까지만 확정", self.turn_id)
            await self._cancel()
        log.info("turn %s stopped: %d bytes audio", self.turn_id, self._audio_bytes)

    async def abort(self) -> None:
        self._close_input()
        await self._cancel()

    def _close_input(self) -> None:
        if not self._input_closed:
            self._input_closed = True
            self._queue.put_nowait(None)

    async def _cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _pcm(self) -> AsyncIterator[bytes]:
        while (chunk := await self._queue.get()) is not None:
            yield chunk

    async def _run(self) -> None:
        try:
            async for event in self._stt.transcribe(self._pcm()):
                if event.kind == "final":
                    await self._store.add_final(self.turn_id, event.text)
                await self._emit(_to_message(event))
        except STTError as e:
            log.error("turn %s: %s", self.turn_id, e)
            await self._emit(ErrorMessage(code="STT_UNAVAILABLE", message=str(e)))
        except Exception:
            log.exception("turn %s: unexpected STT failure", self.turn_id)
            await self._emit(
                ErrorMessage(code="INTERNAL", message="음성 인식 중 오류가 발생했습니다")
            )


class RecordingService:
    def __init__(self, stt: STTEngine, store: TranscriptStore, finalize_timeout_s: float) -> None:
        self._stt = stt
        self._store = store
        self._finalize_timeout_s = finalize_timeout_s

    async def new_turn(self, emit: Emit) -> TurnRecording:
        """새 녹음 구간을 만든다. 시작은 호출자가 started를 보낸 뒤 begin()으로 한다."""
        turn_id = uuid.uuid4().hex
        await self._store.open_turn(turn_id)
        return TurnRecording(turn_id, self._stt, self._store, emit, self._finalize_timeout_s)

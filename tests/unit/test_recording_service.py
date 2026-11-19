import asyncio
from collections.abc import AsyncIterator

from pcm import chunks, tone

from manura.adapters.repo.memory import InMemoryTranscriptStore
from manura.adapters.stt.fake import FakeSTTEngine
from manura.domain.errors import STTError
from manura.domain.models import (
    ErrorMessage,
    FinalMessage,
    PartialMessage,
    ServerMessage,
    TranscriptEvent,
)
from manura.services.recording import RecordingService


class Collector:
    def __init__(self) -> None:
        self.messages: list[ServerMessage] = []

    async def __call__(self, message: ServerMessage) -> None:
        self.messages.append(message)


async def test_turn_emits_partials_and_finals() -> None:
    stt = FakeSTTEngine(sample_rate=16000, script=["하나 둘"], chunks_per_word=1)
    service = RecordingService(stt, InMemoryTranscriptStore(10), finalize_timeout_s=1)
    out = Collector()
    turn = await service.new_turn(out)
    turn.begin()
    for c in chunks(tone(300)):
        turn.feed(c)
    await turn.stop()
    assert out.messages[:3] == [
        PartialMessage(text="하나"),
        PartialMessage(text="하나 둘"),
        FinalMessage(text="하나 둘", start_ms=0, end_ms=200),
    ]


async def test_stop_flushes_unfinished_sentence() -> None:
    stt = FakeSTTEngine(sample_rate=16000, script=["가 나 다 라"], chunks_per_word=1)
    out = Collector()
    turn = await RecordingService(stt, InMemoryTranscriptStore(10), finalize_timeout_s=1).new_turn(
        out
    )
    turn.begin()
    for c in chunks(tone(200)):
        turn.feed(c)
    await turn.stop()
    finals = [m for m in out.messages if isinstance(m, FinalMessage)]
    assert [f.text for f in finals] == ["가 나"]


class HangingSTT:
    async def transcribe(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        async for _ in pcm:
            pass
        yield TranscriptEvent(kind="partial", text="확정 대기")
        await asyncio.sleep(3600)


async def test_stop_times_out_without_hanging() -> None:
    out = Collector()
    turn = await RecordingService(
        HangingSTT(), InMemoryTranscriptStore(10), finalize_timeout_s=0.05
    ).new_turn(out)
    turn.begin()
    turn.feed(tone(100))
    await asyncio.wait_for(turn.stop(), timeout=1)
    assert out.messages == [PartialMessage(text="확정 대기")]


class BrokenSTT:
    async def transcribe(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        raise STTError("연결 실패")
        yield TranscriptEvent(kind="partial", text="")  # pragma: no cover


async def test_stt_error_is_reported() -> None:
    out = Collector()
    turn = await RecordingService(
        BrokenSTT(), InMemoryTranscriptStore(10), finalize_timeout_s=1
    ).new_turn(out)
    turn.begin()
    await turn.stop()
    assert out.messages == [ErrorMessage(code="STT_UNAVAILABLE", message="연결 실패")]

"""실제 OpenAI Realtime 전사 연결 확인. `uv run pytest -m live`로만 실행된다.

합성음(사인파)을 보내므로 인식 텍스트는 비어 있을 수 있다.
세션 설정이 받아들여지고, commit 후 종료까지 오류 없이 도는지를 확인한다.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from pcm import chunks, silence, tone

from manura.adapters.stt.openai_realtime import OpenAIRealtimeSTT
from manura.config import Settings
from manura.domain.models import TranscriptEvent

pytestmark = pytest.mark.live


async def _audio() -> AsyncIterator[bytes]:
    for c in chunks(tone(1000) + silence(800) + tone(500)):
        yield c
        await asyncio.sleep(0.01)


async def test_openai_transcription_session_roundtrip() -> None:
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY 없음")
    stt = OpenAIRealtimeSTT(settings)
    events: list[TranscriptEvent] = []

    async def run() -> None:
        async for event in stt.transcribe(_audio()):
            events.append(event)

    await asyncio.wait_for(run(), timeout=30)
    assert all(e.kind in ("partial", "final") for e in events)

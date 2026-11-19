"""OpenAI Realtime API 전사(transcription) 세션 어댑터.

사양 출처: https://developers.openai.com/api/docs/guides/realtime-transcription (2026-11 확인)
- wss://api.openai.com/v1/realtime?intent=transcription, Authorization: Bearer
- session.update { type: "transcription",
  audio.input: format(audio/pcm, 24000), transcription, turn_detection: null }
- gpt-live-transcribe는 server_vad를 지원하지 않는다 → 클라이언트 측 분할(Segmenter) 후 commit
- 서버 이벤트: input_audio_buffer.committed,
  conversation.item.input_audio_transcription.{delta,completed,failed}
- 서로 다른 commit의 completed는 순서가 뒤바뀔 수 있다 → item_id로 맞추고 commit 순서대로 확정
"""

import asyncio
import base64
import json
import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from manura.adapters.stt.resample import LinearResampler
from manura.adapters.stt.segmenter import Segmenter
from manura.config import Settings
from manura.domain.errors import STTError
from manura.domain.models import TranscriptEvent

log = logging.getLogger(__name__)

_EV_COMMITTED = "input_audio_buffer.committed"
_EV_DELTA = "conversation.item.input_audio_transcription.delta"
_EV_COMPLETED = "conversation.item.input_audio_transcription.completed"
_EV_FAILED = "conversation.item.input_audio_transcription.failed"
_ERR_COMMIT_EMPTY = "input_audio_buffer_commit_empty"


class TranscriptAssembler:
    """OpenAI 이벤트를 commit 순서대로 정리해 partial/final 이벤트로 바꾼다."""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._text: dict[str, str] = {}
        self._result: dict[str, str | None] = {}
        self._span: dict[str, tuple[int, int]] = {}
        self._pending_spans: deque[tuple[int, int]] = deque()
        self._finished: set[str] = set()
        self._last_partial = ""

    @property
    def idle(self) -> bool:
        """보낸 commit이 모두 확인됐고 확정 대기 중인 구간이 없으면 True."""
        return not self._pending_spans and not self._order

    def committing(self, start_ms: int, end_ms: int) -> None:
        self._pending_spans.append((start_ms, end_ms))

    def commit_rejected(self) -> None:
        if self._pending_spans:
            self._pending_spans.popleft()

    def committed(self, item_id: str) -> None:
        span = self._pending_spans.popleft() if self._pending_spans else (0, 0)
        if item_id in self._finished:
            return
        self._see(item_id)
        self._span[item_id] = span

    def delta(self, item_id: str, text: str) -> list[TranscriptEvent]:
        if item_id in self._finished:
            return []
        self._see(item_id)
        self._text[item_id] += text
        return self._partial_if_changed()

    def completed(self, item_id: str, transcript: str) -> list[TranscriptEvent]:
        return self._resolve(item_id, transcript.strip())

    def failed(self, item_id: str) -> list[TranscriptEvent]:
        return self._resolve(item_id, None)

    def _see(self, item_id: str) -> None:
        if item_id not in self._text:
            self._order.append(item_id)
            self._text[item_id] = ""

    def _resolve(self, item_id: str, text: str | None) -> list[TranscriptEvent]:
        if item_id in self._finished:
            return []
        self._see(item_id)
        self._result[item_id] = text
        events: list[TranscriptEvent] = []
        while self._order and self._order[0] in self._result:
            head = self._order.pop(0)
            final = self._result.pop(head)
            self._text.pop(head)
            start_ms, end_ms = self._span.pop(head, (0, 0))
            self._finished.add(head)
            if final:
                events.append(
                    TranscriptEvent(kind="final", text=final, start_ms=start_ms, end_ms=end_ms)
                )
        return events + self._partial_if_changed()

    def _partial_if_changed(self) -> list[TranscriptEvent]:
        # 앞 구간을 기다리느라 보류된 완료 텍스트도 화면에서 사라지지 않게 partial에 포함한다
        pending = (self._result.get(i) or self._text[i] for i in self._order)
        partial = " ".join(t.strip() for t in pending if t.strip())
        if partial == self._last_partial:
            return []
        self._last_partial = partial
        return [TranscriptEvent(kind="partial", text=partial)]


@dataclass(frozen=True)
class _SenderDone:
    pass


@dataclass(frozen=True)
class _Closed:
    error: Exception | None


_Item = dict[str, Any] | _SenderDone | _Closed


class OpenAIRealtimeSTT:
    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise STTError("OPENAI_API_KEY가 설정되지 않았습니다 (.env 확인)")
        self._s = settings
        self._api_key = settings.openai_api_key.get_secret_value()

    async def transcribe(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        try:
            async with connect(
                self._s.openai_realtime_url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                open_timeout=self._s.openai_stt_connect_timeout_s,
                max_size=None,
            ) as ws:
                await self._configure(ws)
                async for event in self._stream(ws, pcm):
                    yield event
        except (WebSocketException, OSError, TimeoutError) as e:
            raise STTError(f"OpenAI STT 연결 실패: {type(e).__name__}") from e

    def _session_update(self) -> dict[str, Any]:
        transcription: dict[str, Any] = {"model": self._s.openai_stt_model}
        if self._s.openai_stt_language:
            transcription["language"] = self._s.openai_stt_language
        if self._s.openai_stt_prompt:
            transcription["prompt"] = self._s.openai_stt_prompt
        if self._s.openai_stt_delay:
            transcription["delay"] = self._s.openai_stt_delay
        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": self._s.openai_stt_sample_rate},
                        "transcription": transcription,
                        "turn_detection": None,
                    }
                },
            },
        }

    async def _configure(self, ws: ClientConnection) -> None:
        await ws.send(json.dumps(self._session_update()))
        async with asyncio.timeout(self._s.openai_stt_connect_timeout_s):
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") == "session.updated":
                    return
                if event.get("type") == "error":
                    raise STTError(_describe_error(event))
        raise STTError("세션 설정 전에 연결이 닫혔습니다")

    async def _stream(
        self, ws: ClientConnection, pcm: AsyncIterator[bytes]
    ) -> AsyncIterator[TranscriptEvent]:
        asm = TranscriptAssembler()
        queue: asyncio.Queue[_Item] = asyncio.Queue()
        recv_task = asyncio.create_task(_receive(ws, queue))
        send_task = asyncio.create_task(self._send_audio(ws, pcm, asm))
        send_task.add_done_callback(lambda _: queue.put_nowait(_SenderDone()))
        sender_done = False
        try:
            while not (sender_done and asm.idle):
                item = await queue.get()
                if isinstance(item, _SenderDone):
                    sender_done = True
                    if (exc := send_task.exception()) is not None:
                        raise STTError(f"오디오 전송 실패: {type(exc).__name__}") from exc
                elif isinstance(item, _Closed):
                    raise STTError("OpenAI 연결이 닫혔습니다") from item.error
                else:
                    for event in _handle(item, asm):
                        yield event
        finally:
            for task in (recv_task, send_task):
                task.cancel()
            await asyncio.gather(recv_task, send_task, return_exceptions=True)

    async def _send_audio(
        self, ws: ClientConnection, pcm: AsyncIterator[bytes], asm: TranscriptAssembler
    ) -> None:
        in_rate = self._s.input_sample_rate
        resampler = LinearResampler(in_rate, self._s.openai_stt_sample_rate)
        segmenter = Segmenter(
            sample_rate=in_rate,
            threshold_dbfs=self._s.stt_vad_threshold_dbfs,
            silence_ms=self._s.stt_vad_silence_ms,
            max_segment_ms=self._s.stt_max_segment_ms,
            min_commit_ms=self._s.stt_min_commit_ms,
        )
        bytes_per_ms = in_rate * 2 / 1000
        pos_ms = 0.0
        seg_start_ms = 0.0
        commits = 0
        async for raw_chunk in pcm:
            chunk = raw_chunk[: len(raw_chunk) - len(raw_chunk) % 2]
            if not chunk:
                continue
            audio = base64.b64encode(resampler.process(chunk)).decode("ascii")
            await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio}))
            pos_ms += len(chunk) / bytes_per_ms
            if segmenter.push(chunk):
                asm.committing(round(seg_start_ms), round(pos_ms))
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                seg_start_ms = pos_ms
                commits += 1
        if segmenter.flush():
            asm.committing(round(seg_start_ms), round(pos_ms))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            commits += 1
        log.info("stt audio sent: %.0f ms, %d commits", pos_ms, commits)


async def _receive(ws: ClientConnection, queue: "asyncio.Queue[_Item]") -> None:
    try:
        async for raw in ws:
            queue.put_nowait(json.loads(raw))
        queue.put_nowait(_Closed(None))
    except WebSocketException as e:
        queue.put_nowait(_Closed(e))


def _handle(event: dict[str, Any], asm: TranscriptAssembler) -> list[TranscriptEvent]:
    kind = event.get("type")
    item_id = str(event.get("item_id", ""))
    if kind == _EV_COMMITTED:
        asm.committed(item_id)
    elif kind == _EV_DELTA:
        return asm.delta(item_id, str(event.get("delta", "")))
    elif kind == _EV_COMPLETED:
        return asm.completed(item_id, str(event.get("transcript", "")))
    elif kind == _EV_FAILED:
        log.warning("stt item failed: %s", item_id)
        return asm.failed(item_id)
    elif kind == "error":
        if event.get("error", {}).get("code") == _ERR_COMMIT_EMPTY:
            asm.commit_rejected()
        else:
            raise STTError(_describe_error(event))
    return []


def _describe_error(event: dict[str, Any]) -> str:
    error = event.get("error", {})
    return f"OpenAI STT 오류 [{error.get('code')}]: {error.get('message')}"

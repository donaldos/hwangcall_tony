import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

from manura.domain.errors import (
    AdviceInProgressError,
    EmptyTranscriptError,
    TurnNotFoundError,
)
from manura.domain.models import AdviceContext, ClientProfile, PromptSet
from manura.domain.ports import LLMAdvisor, TranscriptStore

log = logging.getLogger(__name__)


def load_prompts(system_path: Path, user_path: Path) -> PromptSet:
    return PromptSet(
        system=system_path.read_text(encoding="utf-8"),
        user_template=user_path.read_text(encoding="utf-8"),
    )


def render_advice(prompts: PromptSet, ctx: AdviceContext) -> str:
    return prompts.render({"profile": ctx.profile.describe(), "transcript": ctx.transcript})


class AdviceService:
    def __init__(self, llm: LLMAdvisor, store: TranscriptStore, prompts: PromptSet) -> None:
        self._llm = llm
        self._store = store
        self._prompts = prompts
        self._active: set[str] = set()

    async def begin(self, turn_id: str, profile: ClientProfile | None = None) -> AsyncIterator[str]:
        """검증을 마친 뒤 답변 스트림을 돌려준다. 검증 실패는 스트림 시작 전에 예외로 알린다."""
        transcript = await self._store.turn_text(turn_id)
        if transcript is None:
            raise TurnNotFoundError(turn_id)
        if not transcript.strip():
            raise EmptyTranscriptError(turn_id)
        if turn_id in self._active:
            raise AdviceInProgressError(turn_id)
        self._active.add(turn_id)
        ctx = AdviceContext(transcript=transcript, profile=profile or ClientProfile())
        return self._stream(turn_id, ctx)

    async def _stream(self, turn_id: str, ctx: AdviceContext) -> AsyncIterator[str]:
        started = time.perf_counter()
        first_token_ms: float | None = None
        chars = 0
        try:
            user = render_advice(self._prompts, ctx)
            async for delta in self._llm.stream(self._prompts.system, user):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - started) * 1000
                chars += len(delta)
                yield delta
        finally:
            self._active.discard(turn_id)
            log.info(
                "advice turn %s: transcript %d chars, first token %s ms, total %.0f ms, %d chars",
                turn_id,
                len(ctx.transcript),
                f"{first_token_ms:.0f}" if first_token_ms is not None else "-",
                (time.perf_counter() - started) * 1000,
                chars,
            )

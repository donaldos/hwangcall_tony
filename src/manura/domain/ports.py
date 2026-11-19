from collections.abc import AsyncIterator
from typing import Protocol

from manura.domain.models import SessionRecord, TranscriptEvent


# 스트리밍 메서드는 `def ... -> AsyncIterator`로 선언한다.
# 구현체는 `async def` + `yield`(async generator)로 쓰며, 이래야 mypy --strict에서 맞는다.
class STTEngine(Protocol):
    def transcribe(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        """16kHz mono PCM16 청크를 받아 부분(partial)/최종(final) 결과를 흘려보낸다.
        입력 스트림이 끝나면 남은 최종 결과를 모두 내보낸 뒤 종료한다."""
        ...


class LLMAdvisor(Protocol):
    def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """렌더링이 끝난 시스템/사용자 프롬프트를 받아 답변을 조각(delta) 단위로 스트리밍한다.
        프롬프트 구성은 서비스가 한다 (AI 의견, 세션 정리가 같은 어댑터를 쓴다)."""
        ...


class TranscriptStore(Protocol):
    """녹음 구간별 확정 전사문 저장소. 지금은 메모리, 나중에 SQLite로 교체한다."""

    async def open_turn(self, turn_id: str) -> None: ...

    async def add_final(self, turn_id: str, text: str) -> None: ...

    async def turn_text(self, turn_id: str) -> str | None:
        """확정 전사문을 이어 붙여 돌려준다. 없는 구간이면 None."""
        ...


class SessionArchive(Protocol):
    """[저장]한 상담 기록 보관소."""

    async def save(
        self, record_id: str, record: SessionRecord, summary: str | None, saved_at: str
    ) -> None:
        """record_id로 저장한다. 이미 있으면 내용을 갱신한다(대화는 통째로 교체)."""
        ...

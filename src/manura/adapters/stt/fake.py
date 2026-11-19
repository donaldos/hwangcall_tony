from collections.abc import AsyncIterator, Sequence
from itertools import cycle

from manura.domain.models import TranscriptEvent

DEFAULT_SCRIPT: tuple[str, ...] = (
    "여보세요 네 상담 받고 싶어서 전화드렸어요",
    "요즘 회사 일 때문에 너무 힘들어서요",
    "이직을 해야 할지 계속 버텨야 할지 모르겠어요",
    "네 카드 한번 뽑아볼게요 잠시만요",
)


class FakeSTTEngine:
    """네트워크 없이 동작하는 STT. 오디오 청크 수에 맞춰 대본을 한 단어씩 내보낸다."""

    def __init__(
        self,
        sample_rate: int,
        script: Sequence[str] = DEFAULT_SCRIPT,
        chunks_per_word: int = 3,
    ) -> None:
        self._bytes_per_ms = sample_rate * 2 / 1000
        self._script = script
        self._chunks_per_word = chunks_per_word

    async def transcribe(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        sentences = cycle(self._script)
        words = next(sentences).split()
        spoken: list[str] = []
        pos_ms = 0
        seg_start = 0
        count = 0
        async for chunk in pcm:
            count += 1
            pos_ms += round(len(chunk) / self._bytes_per_ms)
            if count % self._chunks_per_word:
                continue
            spoken.append(words[len(spoken)])
            yield TranscriptEvent(kind="partial", text=" ".join(spoken))
            if len(spoken) == len(words):
                yield TranscriptEvent(
                    kind="final", text=" ".join(spoken), start_ms=seg_start, end_ms=pos_ms
                )
                yield TranscriptEvent(kind="partial", text="")
                words, spoken, seg_start = next(sentences).split(), [], pos_ms
        if spoken:
            yield TranscriptEvent(
                kind="final", text=" ".join(spoken), start_ms=seg_start, end_ms=pos_ms
            )
            yield TranscriptEvent(kind="partial", text="")

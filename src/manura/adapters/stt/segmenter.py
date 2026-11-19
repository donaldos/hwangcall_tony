import math
import sys
from array import array


def chunk_dbfs(pcm: bytes) -> float:
    """PCM16 청크의 RMS 레벨(dBFS). 무음이면 -inf."""
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return -math.inf
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq == 0:
        return -math.inf
    return 10 * math.log10(mean_sq / (32768.0 * 32768.0))


class Segmenter:
    """에너지 기반 클라이언트 측 발화 분할.

    gpt-live-transcribe는 서버 VAD를 지원하지 않으므로 commit 시점을 우리가 정한다.
    발화가 있은 뒤 무음이 silence_ms 이어지거나, 구간이 max_segment_ms를 넘으면 commit한다.
    """

    def __init__(
        self,
        sample_rate: int,
        threshold_dbfs: float,
        silence_ms: int,
        max_segment_ms: int,
        min_commit_ms: int,
    ) -> None:
        self._bytes_per_ms = sample_rate * 2 / 1000
        self._threshold = threshold_dbfs
        self._silence_ms = silence_ms
        self._max_segment_ms = max_segment_ms
        self._min_commit_ms = min_commit_ms
        self._reset()

    def _reset(self) -> None:
        self._uncommitted_ms = 0.0
        self._silence_run_ms = 0.0
        self._had_speech = False

    def push(self, pcm: bytes) -> bool:
        """청크를 반영하고, 이 청크 뒤에 commit해야 하면 True."""
        chunk_ms = len(pcm) / self._bytes_per_ms
        self._uncommitted_ms += chunk_ms
        if chunk_dbfs(pcm) >= self._threshold:
            self._had_speech = True
            self._silence_run_ms = 0.0
        else:
            self._silence_run_ms += chunk_ms
        end_of_speech = self._had_speech and self._silence_run_ms >= self._silence_ms
        if end_of_speech or self._uncommitted_ms >= self._max_segment_ms:
            self._reset()
            return True
        return False

    def flush(self) -> bool:
        """입력이 끝났을 때 남은 오디오를 commit해야 하면 True."""
        should = self._uncommitted_ms >= self._min_commit_ms
        self._reset()
        return should

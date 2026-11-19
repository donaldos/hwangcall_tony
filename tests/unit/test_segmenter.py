from pcm import chunks, silence, tone

from manura.adapters.stt.segmenter import Segmenter, chunk_dbfs


def _segmenter(**overrides: int | float) -> Segmenter:
    params: dict[str, int | float] = {
        "threshold_dbfs": -45.0,
        "silence_ms": 600,
        "max_segment_ms": 15000,
        "min_commit_ms": 100,
    }
    params.update(overrides)
    return Segmenter(sample_rate=16000, **params)  # type: ignore[arg-type]


def _commits(seg: Segmenter, pcm: bytes) -> list[int]:
    """commit이 일어난 청크 인덱스 목록."""
    return [i for i, c in enumerate(chunks(pcm)) if seg.push(c)]


def test_dbfs() -> None:
    assert chunk_dbfs(silence(100)) == float("-inf")
    assert -14 < chunk_dbfs(tone(100, amplitude=0.3)) < -12


def test_commit_after_speech_then_silence() -> None:
    seg = _segmenter()
    commits = _commits(seg, tone(1000) + silence(1000))
    assert commits == [15]  # 말 10청크 + 무음 6청크째


def test_silence_only_does_not_commit_until_max() -> None:
    seg = _segmenter(max_segment_ms=2000)
    assert _commits(seg, silence(3000)) == [19]


def test_long_speech_commits_at_max_segment() -> None:
    seg = _segmenter(max_segment_ms=1000)
    assert _commits(seg, tone(2500)) == [9, 19]


def test_flush_respects_min_commit() -> None:
    seg = _segmenter()
    seg.push(tone(100))
    assert seg.flush() is True
    assert seg.flush() is False

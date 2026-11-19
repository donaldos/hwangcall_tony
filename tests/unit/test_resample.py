from array import array

from pcm import chunks, tone

from manura.adapters.stt.resample import LinearResampler


def _samples(pcm: bytes) -> array[int]:
    out = array("h")
    out.frombytes(pcm)
    return out


def test_16k_to_24k_length_ratio_across_chunks() -> None:
    resampler = LinearResampler(16000, 24000)
    total = sum(len(resampler.process(c)) for c in chunks(tone(1000)))
    expected = 24000 * 2
    assert abs(total - expected) <= 4  # 경계 샘플 1~2개 오차


def test_constant_signal_is_preserved() -> None:
    resampler = LinearResampler(16000, 24000)
    out = _samples(resampler.process(array("h", [1000] * 160).tobytes()))
    assert set(out) == {1000}


def test_chunked_equals_whole() -> None:
    pcm = tone(300)
    whole = LinearResampler(16000, 24000).process(pcm)
    r = LinearResampler(16000, 24000)
    pieces = b"".join(r.process(c) for c in chunks(pcm, ms=10))
    assert pieces == whole


def test_empty_chunk() -> None:
    assert LinearResampler(16000, 24000).process(b"") == b""

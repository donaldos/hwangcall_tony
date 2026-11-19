import sys
from array import array


def _to_samples(pcm: bytes) -> array[int]:
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":  # PCM16은 little-endian
        samples.byteswap()
    return samples


def _to_bytes(samples: array[int]) -> bytes:
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


class LinearResampler:
    """PCM16 mono 스트림을 선형 보간으로 리샘플한다.

    청크 경계에서 끊김이 없도록 직전 청크의 마지막 샘플과 소수 위치를 이어서 쓴다.
    업샘플(16k→24k) 용도라 저역통과 필터는 두지 않는다.
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self._step = src_rate / dst_rate
        self._pos = 0.0
        self._tail: int | None = None

    def process(self, pcm: bytes) -> bytes:
        samples = _to_samples(pcm)
        if not samples:
            return b""
        # buf[0]은 직전 청크의 마지막 샘플이고, 그 뒤로 이번 청크의 샘플이 이어진다.
        buf = samples if self._tail is None else array("h", [self._tail]) + samples
        last = len(buf) - 1
        out = array("h")
        pos = self._pos
        while pos < last:
            i = int(pos)
            frac = pos - i
            out.append(round(buf[i] + (buf[i + 1] - buf[i]) * frac))
            pos += self._step
        self._pos = pos - last
        self._tail = buf[last]
        return _to_bytes(out)

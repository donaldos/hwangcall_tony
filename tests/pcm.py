"""테스트용 합성 PCM16 생성기. 실제 음성 녹음은 쓰지 않는다."""

import math
from array import array


def tone(ms: int, rate: int = 16000, amplitude: float = 0.3, freq: float = 440.0) -> bytes:
    n = rate * ms // 1000
    peak = amplitude * 32767
    return array(
        "h", (round(peak * math.sin(2 * math.pi * freq * i / rate)) for i in range(n))
    ).tobytes()


def silence(ms: int, rate: int = 16000) -> bytes:
    return bytes(rate * ms // 1000 * 2)


def chunks(pcm: bytes, ms: int = 100, rate: int = 16000) -> list[bytes]:
    size = rate * ms // 1000 * 2
    return [pcm[i : i + size] for i in range(0, len(pcm), size)]

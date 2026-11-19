// 마이크 입력을 16kHz mono PCM16 청크로 바꿔 메인 스레드로 보낸다.
// AudioContext를 16kHz로 만들 수 있으면 ratio=1이고 변환만 한다.
// 그렇지 않으면(장치 샘플레이트 고정) 선형 보간으로 다운샘플한다 — 품질은 브라우저 리샘플보다 떨어진다.
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { targetRate, chunkSamples } = options.processorOptions;
    this.ratio = sampleRate / targetRate;
    this.chunkSamples = chunkSamples;
    this.chunk = new Int16Array(chunkSamples);
    this.fill = 0;
    this.pos = 0;
    this.prev = 0;
    this.sumSq = 0;
    this.port.onmessage = (e) => {
      if (e.data === "flush") this.flush();
    };
  }

  push(sample) {
    const s = Math.max(-1, Math.min(1, sample));
    this.sumSq += s * s;
    this.chunk[this.fill++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (this.fill === this.chunkSamples) this.emit(this.chunk, this.fill, false);
  }

  emit(buf, length, flushed) {
    const pcm = buf.slice(0, length).buffer;
    const rms = length ? Math.sqrt(this.sumSq / length) : 0;
    this.port.postMessage({ pcm, rms, flushed }, [pcm]);
    this.fill = 0;
    this.sumSq = 0;
  }

  flush() {
    this.emit(this.chunk, this.fill, true);
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    if (this.ratio === 1) {
      for (let i = 0; i < channel.length; i++) this.push(channel[i]);
      return true;
    }
    // 가상 버퍼: [이전 블록 마지막 샘플, ...이번 블록]
    const n = channel.length;
    let pos = this.pos;
    while (pos < n) {
      const i = Math.floor(pos);
      const frac = pos - i;
      const a = i === 0 ? this.prev : channel[i - 1];
      const b = channel[i];
      this.push(a + (b - a) * frac);
      pos += this.ratio;
    }
    this.pos = pos - n;
    this.prev = channel[n - 1];
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);

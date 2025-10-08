import { useSessionStore } from "../store/useSessionStore";

export type MicCallbacks = {
  onReady: (info: { sampleRate: number }) => Promise<void> | void;
  onChunk: (chunk: ArrayBuffer) => void;
  onStop?: () => void;
};

/**
 * 🔊 改进版 MicRecorder
 * - 使用 AudioWorkletProcessor（Edge / Chrome 均稳定）
 * - 实时推流 16kHz PCM16
 */
export class MicRecorder {
  private ctx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private mediaStream: MediaStream | null = null;
  private capturing = false;
  private callbacks: MicCallbacks | null = null;
  private targetRate = 16000;

  async start(callbacks: MicCallbacks): Promise<void> {
    if (this.capturing) {
      console.warn("[mic] start called while capturing");
      return;
    }

    const store = useSessionStore.getState();
    store.setMicStatus("starting");
    store.setMicError(null);

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      console.info("[mic] ✅ getUserMedia success");
    } catch (err) {
      console.error("[mic] ❌ getUserMedia failed", err);
      store.setMicStatus("error");
      store.setMicError("无法访问麦克风");
      throw err;
    }

    // 🔹 创建 AudioContext + 加载 Worklet
    this.ctx = new AudioContext({ sampleRate: 48000 });
    await this.ctx.audioWorklet.addModule(
      URL.createObjectURL(
        new Blob(
          [
            `
            class MicProcessor extends AudioWorkletProcessor {
              constructor() {
                super();
                this._buf = [];
                this._lastSend = 0;
              }
              process(inputs) {
                const ch = inputs[0][0];
                if (!ch) return true;
                const now = currentTime;
                this._buf.push(new Float32Array(ch));
                if (now - this._lastSend > 0.2) { // 每200ms推一次
                  const merged = this._merge();
                  this.port.postMessage(merged);
                  this._buf = [];
                  this._lastSend = now;
                }
                return true;
              }
              _merge() {
                const len = this._buf.reduce((a,b)=>a+b.length,0);
                const out = new Float32Array(len);
                let off=0;
                for(const c of this._buf){out.set(c,off);off+=c.length;}
                return out;
              }
            }
            registerProcessor('mic-processor', MicProcessor);
            `,
          ],
          { type: "application/javascript" }
        )
      )
    );

    const src = this.ctx.createMediaStreamSource(this.mediaStream);
    this.workletNode = new AudioWorkletNode(this.ctx, "mic-processor");
    src.connect(this.workletNode);
    this.workletNode.connect(this.ctx.destination);

    this.workletNode.port.onmessage = (e) => {
      if (!this.capturing) return;
      const float32 = e.data as Float32Array;
      const pcm16 = this.downsampleTo16k(float32, this.ctx!.sampleRate);
      const buf = this.convertFloat32ToInt16(pcm16);
      callbacks.onChunk(buf);
    };

    this.capturing = true;
    this.callbacks = callbacks;

    await this.ctx.resume();
    await callbacks.onReady({ sampleRate: this.targetRate });

    store.setMicStatus("recording");
    console.info("[mic] 🎙️ recording started, sr=", this.ctx.sampleRate);
  }

  stop(): void {
    if (!this.capturing) return;
    console.info("[mic] ⏹ stop");
    this.capturing = false;

    try {
      this.workletNode?.disconnect();
      this.mediaStream?.getTracks().forEach((t) => t.stop());
      this.ctx?.close();
    } catch (err) {
      console.warn("[mic] stop err", err);
    }

    this.ctx = null;
    this.workletNode = null;
    this.mediaStream = null;
    this.callbacks?.onStop?.();
    this.callbacks = null;

    const store = useSessionStore.getState();
    if (store.micStatus !== "error") store.setMicStatus("idle");
  }

  private downsampleTo16k(input: Float32Array, fromRate: number): Float32Array {
    if (fromRate === this.targetRate) return input;
    const ratio = fromRate / this.targetRate;
    const outLen = Math.round(input.length / ratio);
    const out = new Float32Array(outLen);
    let pos = 0, idx = 0;
    while (pos < outLen) {
      const nextIdx = Math.round((pos + 1) * ratio);
      let sum = 0, count = 0;
      for (let i = idx; i < nextIdx && i < input.length; i++) {
        sum += input[i]; count++;
      }
      out[pos++] = sum / count;
      idx = nextIdx;
    }
    return out;
  }

  private convertFloat32ToInt16(buffer: Float32Array): ArrayBuffer {
    const out = new ArrayBuffer(buffer.length * 2);
    const view = new DataView(out);
    for (let i = 0; i < buffer.length; i++) {
      const s = Math.max(-1, Math.min(1, buffer[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return out;
  }
}

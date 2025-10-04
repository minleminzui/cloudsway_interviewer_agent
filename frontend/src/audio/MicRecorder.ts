import { useSessionStore } from '../store/useSessionStore';

export type MicCallbacks = {
  onReady: (info: { sampleRate: number }) => Promise<void> | void;
  onChunk: (chunk: ArrayBuffer) => void;
  onStop?: () => void;
};

export class MicRecorder {
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private mediaStream: MediaStream | null = null;
  private gain: GainNode | null = null;
  private capturing = false;

  private callbacks: MicCallbacks | null = null;

  async start(callbacks: MicCallbacks): Promise<void> {
    if (this.capturing) {
      console.warn('[mic] start called while capturing; ignoring');
      return;
    }

    const setMicStatus = useSessionStore.getState().setMicStatus;
    const setMicError = useSessionStore.getState().setMicError;

    setMicStatus('starting');
    setMicError(null);

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });
      console.info('[mic] media stream acquired', this.mediaStream.getAudioTracks().map((track) => track.label));
    } catch (error) {
      console.error('[mic] failed to acquire media stream', error);
      setMicStatus('error');
      setMicError(error instanceof Error ? error.message : '无法访问麦克风');
      throw error;
    }

    try {
      this.audioContext = new AudioContext({ sampleRate: 48000 });
      await this.audioContext.resume();
    } catch (error) {
      console.error('[mic] failed to initialise AudioContext', error);
      setMicStatus('error');
      setMicError('浏览器不支持音频上下文');
      this.stop();
      throw error;
    }

    const context = this.audioContext;
    if (!context) {
      throw new Error('音频上下文初始化失败');
    }
    const actualRate = context.sampleRate;
    console.info('[mic] audio context ready', { actualRate });
    try {
      await callbacks.onReady({ sampleRate: actualRate });
    } catch (error) {
      console.error('[mic] onReady callback rejected', error);
      setMicStatus('error');
      setMicError(error instanceof Error ? error.message : '麦克风初始化失败');
      this.stop();
      throw error;
    }

    const bufferSize = 4096;
    this.processor = context.createScriptProcessor(bufferSize, 1, 1);
    this.processor.onaudioprocess = (event) => {
      if (!this.capturing) {
        return;
      }
      const input = event.inputBuffer.getChannelData(0);
      try {
        const pcm = this.convertFloat32ToInt16(input);
        callbacks.onChunk(pcm);
      } catch (error) {
        console.error('[mic] failed to deliver audio chunk', error);
      }
    };

    this.source = context.createMediaStreamSource(this.mediaStream);
    this.gain = context.createGain();
    this.gain.gain.value = 0;

    this.source.connect(this.processor);
    this.processor.connect(this.gain);
    this.gain.connect(context.destination);

    this.capturing = true;
    this.callbacks = callbacks;
    setMicStatus('recording');
    console.info('[mic] recording started');
  }

  stop(): void {
    if (!this.capturing && !this.mediaStream) {
      return;
    }
    console.info('[mic] stopping recorder');
    this.capturing = false;
    try {
      this.processor?.disconnect();
      this.gain?.disconnect();
      this.source?.disconnect();
    } catch (error) {
      console.warn('[mic] disconnect error', error);
    }
    if (this.mediaStream) {
      for (const track of this.mediaStream.getTracks()) {
        track.stop();
      }
    }
    void this.audioContext?.close();
    this.processor = null;
    this.source = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.gain = null;
    this.callbacks?.onStop?.();
    this.callbacks = null;
    const store = useSessionStore.getState();
    if (store.micStatus !== 'error') {
      store.setMicStatus('idle');
    }
  }

  private convertFloat32ToInt16(buffer: Float32Array): ArrayBuffer {
    const len = buffer.length;
    const out = new ArrayBuffer(len * 2);
    const view = new DataView(out);
    for (let i = 0; i < len; i += 1) {
      let sample = buffer[i];
      sample = Math.max(-1, Math.min(1, sample));
      view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return out;
  }
}

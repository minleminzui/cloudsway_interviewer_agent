export class TtsPlayer {
  private audio: HTMLAudioElement;
  private mediaSource: MediaSource | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private queue: ArrayBuffer[] = [];
  private mime: string;

  constructor(mime: string = 'audio/mpeg') {
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.mime = mime;
  }

  prepare() {
    this.disposeMediaSource();
    this.queue = [];
    this.mediaSource = new MediaSource();
    const objectUrl = URL.createObjectURL(this.mediaSource);
    this.audio.src = objectUrl;
    this.mediaSource.addEventListener('sourceopen', () => {
      if (!this.mediaSource) return;
      if (!MediaSource.isTypeSupported(this.mime)) {
        console.warn('[tts] mime not supported by MediaSource', this.mime);
      }
      this.sourceBuffer = this.mediaSource.addSourceBuffer(this.mime);
      this.sourceBuffer.mode = 'sequence';
      this.sourceBuffer.addEventListener('updateend', () => this.drain());
      this.drain();
    }, { once: true });
  }

  enqueue(chunk: ArrayBuffer) {
    this.queue.push(chunk);
    this.drain();
  }

  private drain() {
    if (!this.sourceBuffer || this.sourceBuffer.updating) return;
    const chunk = this.queue.shift();
    if (!chunk) {
      return;
    }
    try {
      this.sourceBuffer.appendBuffer(new Uint8Array(chunk));
      if (this.audio.paused) {
        void this.audio.play().catch(() => undefined);
      }
    } catch (error) {
      console.warn('[tts] append buffer failed, resetting player', error);
      this.cancel();
    }
  }

  finalize() {
    if (this.mediaSource && this.mediaSource.readyState === 'open') {
      try {
        this.mediaSource.endOfStream();
      } catch (error) {
        console.warn('[tts] endOfStream failed', error);
      }
    }
  }

  pause() {
    this.audio.pause();
  }

  cancel() {
    this.queue = [];
    if (this.sourceBuffer && this.mediaSource?.readyState === 'open') {
      try {
        this.sourceBuffer.abort();
      } catch (error) {
        console.warn('[tts] abort error', error);
      }
    }
    this.disposeMediaSource();
    this.audio.pause();
    this.audio.currentTime = 0;
  }

  destroy() {
    this.cancel();
    this.audio.remove();
  }

  private disposeMediaSource() {
    if (this.sourceBuffer && this.mediaSource) {
      try {
        this.mediaSource.removeSourceBuffer(this.sourceBuffer);
      } catch {
        // ignore
      }
    }
    if (this.audio.src) {
      URL.revokeObjectURL(this.audio.src);
      this.audio.removeAttribute('src');
      this.audio.load();
    }
    this.mediaSource = null;
    this.sourceBuffer = null;
  }
}

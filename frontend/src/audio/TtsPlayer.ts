export class TtsPlayer {
  private audio: HTMLAudioElement;
  private mediaSource: MediaSource | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private queue: ArrayBuffer[] = [];
  private blobChunks: ArrayBuffer[] = [];
  private mime: string;
  private objectUrl: string | null = null;
  private useMediaSource = false;
  private blobPlaybackActive = false;
  private forceBlobPlayback = false;

  private readonly handleBlobPlaybackEnded = () => {
    this.blobPlaybackActive = false;
    this.prepare();
  };

  constructor(mime: string = 'audio/mpeg') {
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.mime = mime;
  }

  prepare() {
    this.queue = [];
    this.blobChunks = [];
    if (this.blobPlaybackActive) {
      return;
    }
    this.disposeMediaSource();
    this.useMediaSource = this.canUseMediaSource();
    if (this.useMediaSource) {
      this.mediaSource = new MediaSource();
      const objectUrl = URL.createObjectURL(this.mediaSource);
      this.objectUrl = objectUrl;
      this.audio.src = objectUrl;
      this.mediaSource.addEventListener('sourceopen', () => this.handleSourceOpen(), { once: true });
    } else {
      this.resetAudioElement();
    }
  }

  enqueue(chunk: ArrayBuffer) {
    if (this.useMediaSource) {
      this.queue.push(chunk);
      if (this.queue.length === 1) {
        console.debug('[tts] queued first streaming chunk', { byteLength: chunk.byteLength });
      }
      this.drain();
      return;
    }
    this.blobChunks.push(chunk.slice(0));
    if (this.blobChunks.length === 1) {
      console.debug('[tts] buffering first blob chunk', { byteLength: chunk.byteLength });
    }
  }

  private drain() {
    if (!this.useMediaSource || !this.sourceBuffer || this.sourceBuffer.updating) return;
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
    if (this.useMediaSource) {
      if (this.mediaSource && this.mediaSource.readyState === 'open') {
        try {
          this.mediaSource.endOfStream();
        } catch (error) {
          console.warn('[tts] endOfStream failed', error);
        }
      }
      return;
    }
    if (this.blobChunks.length === 0) {
      return;
    }
    const blob = new Blob(this.blobChunks, { type: this.mime });
    this.queue = [];
    this.revokeObjectUrl();
    this.objectUrl = URL.createObjectURL(blob);
    this.audio.src = this.objectUrl;
    this.blobChunks = [];
    this.audio.removeEventListener('ended', this.handleBlobPlaybackEnded);
    this.audio.addEventListener('ended', this.handleBlobPlaybackEnded, { once: true });
    this.blobPlaybackActive = true;
    console.debug('[tts] prepared blob playback', { mime: this.mime, size: blob.size });
    const playPromise = this.audio.play();
    if (typeof playPromise?.catch === 'function') {
      playPromise.catch(() => {
        this.audio.removeEventListener('ended', this.handleBlobPlaybackEnded);
        this.blobPlaybackActive = false;
      });
    }
  }

  pause() {
    this.audio.pause();
  }

  cancel() {
    this.queue = [];
    this.blobChunks = [];
    this.clearBlobPlaybackListener();
    if (this.useMediaSource) {
      if (this.sourceBuffer && this.mediaSource?.readyState === 'open') {
        try {
          this.sourceBuffer.abort();
        } catch (error) {
          console.warn('[tts] abort error', error);
        }
      }
      this.disposeMediaSource();
    } else {
      this.revokeObjectUrl();
      this.resetAudioElement();
    }
    this.audio.pause();
    this.audio.currentTime = 0;
  }

  destroy() {
    this.cancel();
    this.audio.remove();
  }

  private disposeMediaSource() {
    this.clearBlobPlaybackListener();
    if (this.sourceBuffer && this.mediaSource) {
      try {
        this.mediaSource.removeSourceBuffer(this.sourceBuffer);
      } catch {
        // ignore
      }
    }
    this.mediaSource = null;
    this.sourceBuffer = null;
    this.revokeObjectUrl();
    this.resetAudioElement();
  }

  private handleSourceOpen() {
    if (!this.mediaSource) {
      return;
    }
    const fallbackToBlob = () => {
      this.useMediaSource = false;
      this.forceBlobPlayback = true;
      this.blobChunks.push(...this.queue.map((chunk) => chunk.slice(0)));
      this.queue = [];
      this.disposeMediaSource();
    };
    try {
      if (typeof MediaSource.isTypeSupported === 'function' && !MediaSource.isTypeSupported(this.mime)) {
        console.warn('[tts] mime not supported by MediaSource', this.mime);
        fallbackToBlob();
        return;
      }
      this.sourceBuffer = this.mediaSource.addSourceBuffer(this.mime);
    } catch (error) {
      console.warn('[tts] addSourceBuffer failed, falling back to Blob playback', error);
      fallbackToBlob();
      return;
    }
    if (!this.sourceBuffer) {
      return;
    }
    this.sourceBuffer.mode = 'sequence';
    this.sourceBuffer.addEventListener('updateend', () => this.drain());
    this.drain();
  }

  private canUseMediaSource() {
    if (this.forceBlobPlayback) {
      return false;
    }
    return typeof MediaSource !== 'undefined';
  }

  private resetAudioElement() {
    this.audio.removeAttribute('src');
    this.audio.load();
  }

  private revokeObjectUrl() {
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
  }

  private clearBlobPlaybackListener() {
    this.audio.removeEventListener('ended', this.handleBlobPlaybackEnded);
    this.blobPlaybackActive = false;
  }

  isUsingMediaSource() {
    return this.useMediaSource;
  }

  isBlobPlaybackActive() {
    return this.blobPlaybackActive;
  }
}

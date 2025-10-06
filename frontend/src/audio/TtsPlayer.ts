// src/audio/TtsPlayer.ts
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
  private autoplayUnlocked = false;

  private readonly handleBlobPlaybackEnded = () => {
    this.blobPlaybackActive = false;
    this.prepare();
  };

  constructor(mime: string = 'audio/ogg; codecs="opus"') {
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.audio.autoplay = true;
    this.audio.muted = true; // ✅ 初始静音以绕过浏览器 autoplay 限制
    this.mime = mime;

    // ✅ 自动注册点击 / 键盘交互监听（仅一次）
    const unlockPlayback = () => {
      if (!this.autoplayUnlocked) {
        this.autoplayUnlocked = true;
        this.audio.muted = false;
        console.info('[tts] 🎧 user interacted, unmuted audio playback');
      }
      document.removeEventListener('click', unlockPlayback);
      document.removeEventListener('keydown', unlockPlayback);
    };
    document.addEventListener('click', unlockPlayback, { once: true });
    document.addEventListener('keydown', unlockPlayback, { once: true });

    console.info('[tts] Player initialized', {
      mime: this.mime,
      autoplay: this.audio.autoplay,
      muted: this.audio.muted,
    });
  }

  prepare() {
    this.queue = [];
    this.blobChunks = [];
    if (this.blobPlaybackActive) return;

    this.disposeMediaSource();
    this.useMediaSource = this.canUseMediaSource();

    if (this.useMediaSource) {
      this.mediaSource = new MediaSource();
      const objectUrl = URL.createObjectURL(this.mediaSource);
      this.objectUrl = objectUrl;
      this.audio.src = objectUrl;

      console.info('[tts] preparing MediaSource for stream', { mime: this.mime });
      this.mediaSource.addEventListener('sourceopen', () => this.handleSourceOpen(), { once: true });
    } else {
      console.warn('[tts] MediaSource not supported, will use blob fallback');
      this.resetAudioElement();
    }
  }

  enqueue(chunk: ArrayBuffer) {
    if (this.useMediaSource) {
      this.queue.push(chunk);
      console.debug('[tts] enqueue chunk', {
        chunkBytes: chunk.byteLength,
        pendingQueue: this.queue.length,
      });
      this.drain();
      return;
    }

    this.blobChunks.push(chunk.slice(0));
    console.debug('[tts] buffering blob chunk', { byteLength: chunk.byteLength });
  }

  private drain() {
    if (!this.useMediaSource || !this.sourceBuffer || this.sourceBuffer.updating) return;
    const chunk = this.queue.shift();
    if (!chunk) return;

    try {
      this.sourceBuffer.appendBuffer(new Uint8Array(chunk));
      console.debug('[tts] appended chunk', {
        appended: chunk.byteLength,
        remaining: this.queue.length,
      });
      if (this.audio.paused) {
        void this.safePlay();
      }
    } catch (error) {
      console.warn('[tts] appendBuffer failed, resetting player', error);
      this.cancel();
    }
  }

  finalize() {
    if (this.useMediaSource) {
      if (this.mediaSource && this.mediaSource.readyState === 'open') {
        const tryEnd = () => {
          if (this.sourceBuffer && this.sourceBuffer.updating) {
            setTimeout(tryEnd, 100);
            return;
          }
          try {
            this.mediaSource!.endOfStream();
            console.debug('[tts] MediaSource endOfStream called');
          } catch (err) {
            console.warn('[tts] endOfStream retry failed', err);
          }
        };
        tryEnd();
      }
      return;
    }

    if (this.blobChunks.length === 0) return;
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
    void this.safePlay();
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

  private async safePlay() {
    try {
      await this.audio.play();
      console.debug('[tts] playback started successfully');
    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        console.warn('[tts] autoplay blocked by browser, waiting for user interaction');
        const unlock = () => {
          console.info('[tts] user clicked, retrying playback');
          this.audio.play().catch(() => {});
          document.removeEventListener('click', unlock);
          document.removeEventListener('keydown', unlock);
        };
        document.addEventListener('click', unlock, { once: true });
        document.addEventListener('keydown', unlock, { once: true });
      } else {
        console.warn('[tts] playback failed', err);
      }
    }
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
    if (!this.mediaSource) return;
    console.debug('[tts] handleSourceOpen called', { mime: this.mime });

    const fallbackToBlob = () => {
      console.warn('[tts] fallbackToBlob triggered');
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
      console.debug('[tts] sourceBuffer created successfully');
    } catch (error) {
      console.warn('[tts] addSourceBuffer failed, falling back to Blob playback', error);
      fallbackToBlob();
      return;
    }

    if (!this.sourceBuffer) return;
    this.sourceBuffer.mode = 'sequence';
    this.sourceBuffer.addEventListener('updateend', () => this.drain());
    this.drain();
  }

  private canUseMediaSource() {
    if (this.forceBlobPlayback) return false;
    const supported = typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported?.(this.mime);
    console.debug('[tts] canUseMediaSource', { supported, mime: this.mime });
    return !!supported;
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

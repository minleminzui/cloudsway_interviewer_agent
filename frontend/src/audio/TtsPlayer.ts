// src/audio/TtsPlayer.ts
const DEBUG_TTS = true;

export class TtsPlayer {
  private audio: HTMLAudioElement;
  private objectUrl: string | null = null;
  private mime = "audio/mpeg";
  private blobChunks: BlobPart[] = [];
  private destroyed = false;
  private unlockPromptEl: HTMLDivElement | null = null;

  constructor(mime?: string) {
    if (mime) this.mime = mime;

    this.audio = new Audio();
    this.audio.autoplay = true;
    this.audio.muted = false;
    this.audio.volume = 1;
    this.audio.preload = "auto";
    this.audio.controls = false;

    // 兼容 iOS 行内播放
    this.audio.setAttribute("playsinline", "");
    this.audio.setAttribute("webkit-playsinline", "true");

    // 确保 <audio> 在 DOM 中（不可见）
    this.audio.style.position = "fixed";
    this.audio.style.left = "-10000px";
    this.audio.style.top = "0";
    this.audio.style.width = "1px";
    this.audio.style.height = "1px";
    this.audio.style.opacity = "0";
    this.audio.setAttribute("aria-hidden", "true");
    document.body.appendChild(this.audio);

    this.audio.onplaying = () => DEBUG_TTS && console.info("[tts] ▶️ onplaying");
    this.audio.onended = () => DEBUG_TTS && console.info("[tts] ⏹️ onended");
    this.audio.onerror = (e) => DEBUG_TTS && console.error("[tts] audio error", e);

    DEBUG_TTS &&
      console.info("[tts] Player initialized", {
        mime: this.mime,
        autoplay: this.audio.autoplay,
        muted: this.audio.muted,
      });
  }

  /** 兼容旧调用签名；内部不使用该参数 */
  prepare(_forceBlob?: boolean) {
    if (this.destroyed) return;
    this.blobChunks = [];
    this.stopInternal();
    console.warn("[tts] Fallback to Blob playback");
  }

  enqueue(chunk: ArrayBuffer) {
    if (this.destroyed) return;
    const part = new Uint8Array(chunk);
    this.blobChunks.push(part);
    DEBUG_TTS && console.info("[tts] 📦 enqueue", part.byteLength);
  }

  async finalize() {
    if (this.destroyed) return;
    if (this.blobChunks.length === 0) {
      DEBUG_TTS && console.warn("[tts] no blobChunks to finalize");
      return;
    }

    try {
      const blob = new Blob(this.blobChunks, { type: this.mime || "audio/mpeg" });
      DEBUG_TTS && console.info("[tts] 🔚 finalize: blob size:", blob.size, "type:", blob.type);

      this.revokeObjectUrl();
      this.objectUrl = URL.createObjectURL(blob);

      this.audio.src = this.objectUrl;
      this.audio.load();

      // 监听就绪事件，尝试播放
      const tryNow = () => void this.tryPlayWithUnlock();
      this.audio.addEventListener("loadeddata", tryNow, { once: true });
      this.audio.addEventListener("canplay", tryNow, { once: true });
      this.audio.addEventListener("canplaythrough", tryNow, { once: true });

      // 也马上尝试一次
      await this.tryPlayWithUnlock();
    } catch (err) {
      console.error("[tts] blob finalize failed:", err);
    } finally {
      this.blobChunks = [];
    }
  }

  cancel() {
    this.stopInternal();
  }

  destroy() {
    this.destroyed = true;
    this.stopInternal();
    try {
      this.audio.remove();
    } catch {}
    if (this.unlockPromptEl) this.unlockPromptEl.remove();
  }

  // --- 内部 ---
  private stopInternal() {
    try {
      this.audio.pause();
    } catch {}
    this.audio.removeAttribute("src");
    try {
      this.audio.load();
    } catch {}
    this.revokeObjectUrl();
  }

  private revokeObjectUrl() {
    if (this.objectUrl) {
      try {
        URL.revokeObjectURL(this.objectUrl);
      } catch {}
      this.objectUrl = null;
    }
  }

  private showUnlockPrompt() {
    if (this.unlockPromptEl || document.getElementById("__tts-unlock-tip")) return;

    const box = document.createElement("div");
    box.id = "__tts-unlock-tip";
    box.textContent = "🔊 点击开启音频";
    box.style.cssText =
      "position:fixed;right:16px;bottom:16px;padding:10px 12px;border-radius:12px;background:#111;color:#fff;font:14px/1.2 system-ui;cursor:pointer;z-index:99999;box-shadow:0 4px 14px rgba(0,0,0,.2);opacity:.92";
    const click = () => {
      this.unlock().catch(() => {});
      box.remove();
      this.unlockPromptEl = null;
    };
    box.addEventListener("click", click, { once: true });
    document.body.appendChild(box);
    this.unlockPromptEl = box;
  }

  /** 主播放逻辑；若被策略拦截，则等待下一次用户手势解锁 */
  private async tryPlayWithUnlock() {
    if (!this.audio.src) return;

    try {
      this.audio.muted = false;
      this.audio.volume = 1;
      await this.audio.play();
      DEBUG_TTS && console.info("[tts] ▶️ play() ok");
      return;
    } catch (err: any) {
      DEBUG_TTS && console.warn("[tts] play() rejected:", err?.name || String(err));
    }

    // 被自动播放策略拦截：挂一次性手势监听，提示用户点击开启音频
    const unlock = async () => {
      document.removeEventListener("pointerdown", unlock);
      document.removeEventListener("keydown", unlock);
      document.removeEventListener("touchend", unlock);
      await this.unlock();
    };

    document.addEventListener("pointerdown", unlock, { once: true, passive: true });
    document.addEventListener("keydown", unlock, { once: true });
    document.addEventListener("touchend", unlock, { once: true, passive: true });

    this.showUnlockPrompt();
  }

  /** 暴露一个可手动调用的解锁方法（可在按钮/任意点击时调用） */
  public async unlock() {
    if (!this.audio.src) return;
    try {
      // 先静音播放 → 让播放状态进入“允许”
      this.audio.muted = true;
      await this.audio.play().catch(() => {});
      // 下一帧取消静音并确保在播
      await new Promise((r) => setTimeout(r, 60));
      this.audio.muted = false;
      await this.audio.play();
      DEBUG_TTS && console.info("[tts] ▶️ play() ok after gesture");
    } catch (e) {
      DEBUG_TTS && console.warn("[tts] still blocked after gesture:", (e as any)?.name || e);
    }
  }
}

// src/api/ttsClient.ts
import { TtsPlayer } from '../audio/TtsPlayer';
import { useSessionStore } from '../store/useSessionStore';

function makeWsUrl(baseUrl: string, path: string) {
  const backendHost = window.location.hostname;
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsPort = 8000;
  return `${wsProtocol}//${backendHost}:${wsPort}${path}`;
}

export class TtsClient {
  private ws: WebSocket | null = null;
  private player: TtsPlayer | null = null;
  private ready = false;
  private playerMime = 'audio/mpeg';

  private chunkSilenceTimer: number | null = null;
  private readonly SILENCE_MS = 600;

  // 浏览器语音回退
  private speechVoicesReady = false;
  private pendingSpeech: string[] = [];
  private voicesChangedHandler: (() => void) | null = null;
  private fallbackReason: string | null = null;
  private fallbackWatchTimer: number | null = null;
  private fallbackText: string | null = null;
  private fallbackUserActionListener: ((event: Event) => void) | null = null;
  private fallbackUserActionEvents: Array<keyof DocumentEventMap> = ['pointerdown', 'keydown'];

  constructor(public baseUrl: string, public sessionId: string) {}

  public getSessionId(): string {
    return this.sessionId;
  }

  private resetSilenceTimer() {
    if (this.chunkSilenceTimer) clearTimeout(this.chunkSilenceTimer);
    this.chunkSilenceTimer = window.setTimeout(() => {
      // ✅ 没有新块了，自动 finalize 一次（只对 Blob 路径起作用）
      this.player?.finalize();
      this.chunkSilenceTimer = null;
      console.debug('[tts] ⏳ silence reached, auto finalize()');
    }, this.SILENCE_MS);
  }

  connect() {
    this.ensurePlayer();
    this.ensureSpeechVoices();

    const wsUrl = makeWsUrl(this.baseUrl, `/ws/tts?session=${this.sessionId}`);
    this.ws = new WebSocket(wsUrl);
    this.ws.binaryType = 'arraybuffer';

    const { setTtsReady, setTtsMode, setTtsError } = useSessionStore.getState();

    this.ws.onopen = () => {
      console.info('[tts] websocket connected', { sessionId: this.sessionId });
      this.ready = false;
      setTtsReady(false);
      setTtsMode('stream');
      setTtsError(null);
      if (this.chunkSilenceTimer) { clearTimeout(this.chunkSilenceTimer); this.chunkSilenceTimer = null; }

      setTimeout(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          console.info('[tts] handshake confirmed alive', { sessionId: this.sessionId });
        }
      }, 500);
    };

    this.ws.onerror = (event) => {
      console.error('[tts] websocket error', event);
      setTtsError('TTS WebSocket 连接出错');
    };

    this.ws.onmessage = (event) => {
  if (typeof event.data === 'string') {
    this.handleControlMessage(event.data);
    return;
  }
  const ab = event.data as ArrayBuffer;
  console.debug('[tts] 🔹 binary frame', ab.byteLength, 'bytes');
  if (!this.ready) return;
  this.player?.enqueue(ab);
};


    this.ws.onclose = (event) => {
      console.info('[tts] websocket closed', {
        sessionId: this.sessionId,
        code: event.code,
        reason: event.reason,
      });
      this.ready = false;
      useSessionStore.getState().setTtsReady(false);

      // 兜底：如果还有未播完的 blob 分片，收口播掉
      this.player?.finalize();

      const { ttsMode } = useSessionStore.getState();
      if (ttsMode !== 'error' && ttsMode !== 'fallback') {
        useSessionStore.getState().setTtsMode('stream');
        useSessionStore.getState().setTtsError(null);
      }
      if (this.chunkSilenceTimer) { clearTimeout(this.chunkSilenceTimer); this.chunkSilenceTimer = null; }
    };
  }

  private handleTextMessage(raw: string) {
    const { setTtsReady, setTtsMode, setTtsError } = useSessionStore.getState();
    try {
      const payload = JSON.parse(raw);

      // 1) base64 分片
      const b64 = payload?.data || payload?.chunk || payload?.audio || null;
      if (b64 && typeof b64 === 'string') {
        if (!this.ready) return;
        const buf = this.base64ToArrayBuffer(b64);
        this.player?.enqueue(buf);
        this.resetSilenceTimer();
        return;
      }

      // 2) 标准控制消息
      switch (payload.type) {
        case 'tts_ready':
          if (payload.mime) this.playerMime = payload.mime;
          this.ensurePlayer(this.playerMime);
          this.ready = true;
          setTtsReady(true);
          setTtsMode('stream');
          console.info('[tts] stream ready', { mime: this.playerMime, sessionId: this.sessionId });
          break;

        case 'tts_chunk': // 某些后端也会用这个 type 包 base64
          if (payload.data) {
            const buf = this.base64ToArrayBuffer(payload.data);
            this.player?.enqueue(buf);
            this.resetSilenceTimer();
          }
          break;

        case 'tts_end':
          console.info('[tts] <-- tts_end');      
          this.player?.finalize();
          break;

        case 'tts_error':
          this.player?.cancel();
          this.ready = false;
          setTtsReady(false);
          setTtsMode('error');
          setTtsError(payload.message || 'TTS 服务发生错误');
          console.error('[tts] backend reported error', payload.message);
          break;

        case 'tts_fallback':
          this.ready = false;
          setTtsReady(false);
          this.speakFallback(payload.text || '', payload.message);
          break;

        default:
          console.warn('[tts] unknown control message', payload);
      }
    } catch {
      // 既不是 JSON 也不是 ArrayBuffer，就忽略
    }
  }

  private handleControlMessage(raw: string) {
    const { setTtsReady, setTtsMode, setTtsError } = useSessionStore.getState();
    try {
      const payload = JSON.parse(raw);
      switch (payload.type) {
        case 'tts_ready': {
          if (payload.mime) this.playerMime = payload.mime;
          this.ensurePlayer(this.playerMime);
          this.ready = true;
          setTtsReady(true);
          setTtsMode('stream');
          console.info('[tts] stream ready', { mime: this.playerMime, sessionId: this.sessionId });
          break;
        }
        case 'tts_end': {
          // 有就用，没有就走静默超时
          this.player?.finalize();
          break;
        }
        case 'tts_error': {
          this.player?.cancel();
          this.ready = false;
          setTtsReady(false);
          setTtsMode('error');
          setTtsError(payload.message || 'TTS 服务发生错误');
          console.error('[tts] backend reported error', payload.message);
          break;
        }
        case 'tts_fallback': {
          this.ready = false;
          setTtsReady(false);
          this.speakFallback(payload.text || '', payload.message);
          break;
        }
        default:
          console.warn('[tts] unknown control message', payload);
      }
    } catch (err) {
      console.warn('[tts] failed to parse control message', err);
    }
  }

  cancelPlayback() {
    this.player?.cancel();
    this.cancelSpeechFallback();
  }

  close() {
    try {
      this.cancelPlayback();
      this.ws?.close();
    } catch (e) {
      console.warn('[tts] close error', e);
    }
    this.ws = null;
    this.player?.destroy();
    this.player = null;
    this.teardownVoicesListener();
  }

  private ensurePlayer(mime: string = this.playerMime) {
    if (!this.player || this.playerMime !== mime) {
      this.player?.destroy();
      this.player = new TtsPlayer(mime);
      this.playerMime = mime;
    }
    // mp3 统一走 Blob
    const forceBlob = (mime || '').toLowerCase().includes('mpeg') || mime.toLowerCase().includes('mp3');
    this.player.prepare();
  }

  private base64ToArrayBuffer(b64: string): ArrayBuffer {
    const bin = atob(b64);
    const len = bin.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }

  
  // ======= 浏览器语音回退 =======
  public retryFallbackSpeech() {
    if (!this.fallbackText) return;
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    try {
      const synth = window.speechSynthesis;
      // 某些浏览器首次 getVoices() 是空的；尝试触发一次
      const list = synth.getVoices().length ? synth.getVoices() : (synth.getVoices(), synth.getVoices());
      const v = list.find(v => v.lang?.startsWith('zh')) ?? list[0];

      synth.cancel();
      const u = new SpeechSynthesisUtterance(this.fallbackText);
      if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = 'zh-CN'; }
      synth.speak(u);
      console.info('[tts] retryFallbackSpeech started');
    } catch (e) {
      console.warn('[tts] retryFallbackSpeech failed', e);
    }
  }

  private speakFallback(text: string, reason?: string) {
    const fallbackReason = reason?.trim() || '已切换到浏览器语音播报。';
    this.fallbackReason = fallbackReason;
    this.fallbackText = text || null;
    this.updateFallbackState(this.fallbackText, false);
    this.updateTtsMode('fallback', fallbackReason);
    this.ensureFallbackUserActionListener();

    if (!text) return;

    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      console.error('[tts] browser does not support speech synthesis');
      this.updateTtsMode('error', '浏览器不支持语音合成');
      return;
    }

    const synth = window.speechSynthesis;
    if (!this.speechVoicesReady && synth.getVoices().length === 0) {
      this.pendingSpeech.push(text);
      this.ensureSpeechVoices();
      return;
    }

    this.speechVoicesReady = true;
    synth.cancel();
    const utterance = this.buildUtterance(text);
    synth.speak(utterance);
    this.startFallbackWatchdog();
  }

  private ensureSpeechVoices() {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    const synth = window.speechSynthesis;
    const voices = synth.getVoices();
    if (voices.length > 0) {
      this.speechVoicesReady = true;
      this.flushPendingSpeech();
      return;
    }
    if (this.voicesChangedHandler) return;
    this.voicesChangedHandler = () => {
      this.speechVoicesReady = true;
      this.flushPendingSpeech();
    };
    synth.addEventListener('voiceschanged', this.voicesChangedHandler, { once: true });
    synth.getVoices(); // 触发懒加载
  }

  private flushPendingSpeech() {
    if (!this.speechVoicesReady || this.pendingSpeech.length === 0) return;
    const texts = this.pendingSpeech.splice(0);
    for (const text of texts) {
      const utterance = this.buildUtterance(text);
      window.speechSynthesis.speak(utterance);
    }
  }

  private cancelSpeechFallback() {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    this.fallbackText = null;
    this.clearFallbackWatchdog();
    this.updateFallbackState(null, false);
    this.teardownFallbackUserActionListener();
  }

  private teardownVoicesListener() {
    if (this.voicesChangedHandler && 'speechSynthesis' in window) {
      window.speechSynthesis.removeEventListener('voiceschanged', this.voicesChangedHandler);
      this.voicesChangedHandler = null;
    }
  }

  private updateTtsMode(mode: 'stream' | 'fallback' | 'error', error?: string | null) {
    const { setTtsMode, setTtsError } = useSessionStore.getState();
    setTtsMode(mode);
    if (error) setTtsError(error);
  }

  private buildUtterance(text: string) {
    const utterance = new SpeechSynthesisUtterance(text);
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find((v) => v.lang?.startsWith('zh')) ?? voices[0];
    if (preferred) {
      utterance.voice = preferred;
      utterance.lang = preferred.lang;
    } else {
      utterance.lang = 'zh-CN';
    }
    utterance.onend = () => {
      this.updateTtsMode('fallback', this.fallbackReason);
      this.updateFallbackState(null, false);
    };
    utterance.onerror = (e) => {
      console.error('[tts] fallback utterance error', e);
      this.updateTtsMode('error', '语音合成失败');
    };
    return utterance;
  }

  private startFallbackWatchdog() {
    if (this.fallbackWatchTimer) clearTimeout(this.fallbackWatchTimer);
    this.fallbackWatchTimer = window.setTimeout(() => {
      if (!window.speechSynthesis.speaking) {
        const msg = this.fallbackReason ?? '请点击页面后再试';
        this.updateTtsMode('fallback', msg);
        this.updateFallbackState(this.fallbackText, true);
        this.ensureFallbackUserActionListener();
      }
    }, 3000);
  }

  private clearFallbackWatchdog() {
    if (this.fallbackWatchTimer) {
      clearTimeout(this.fallbackWatchTimer);
      this.fallbackWatchTimer = null;
    }
  }

  private updateFallbackState(text: string | null, needUserAction: boolean) {
    const { setTtsFallbackText, setTtsFallbackNeedUserAction } = useSessionStore.getState();
    setTtsFallbackText(text);
    setTtsFallbackNeedUserAction(needUserAction);
  }

  private ensureFallbackUserActionListener() {
    if (!document || !this.fallbackText) return;
    if (this.fallbackUserActionListener) return;
    const handler = () => {
      console.info('[tts] user interaction detected, retrying fallback');
      this.teardownFallbackUserActionListener();
      this.retryFallbackSpeech();
    };
    this.fallbackUserActionListener = handler;
    for (const e of this.fallbackUserActionEvents) {
      document.addEventListener(e, handler, { once: true });
    }
  }

  private teardownFallbackUserActionListener() {
    if (!this.fallbackUserActionListener) return;
    for (const e of this.fallbackUserActionEvents) {
      document.removeEventListener(e, this.fallbackUserActionListener);
    }
    this.fallbackUserActionListener = null;
  }
}

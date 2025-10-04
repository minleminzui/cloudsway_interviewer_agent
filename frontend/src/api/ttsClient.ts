import { TtsPlayer } from '../audio/TtsPlayer';
import { useSessionStore } from '../store/useSessionStore';

function makeWsUrl(baseUrl: string, path: string) {
  const url = new URL(path, baseUrl);
  url.protocol = url.protocol.replace('http', 'ws');
  return url.toString();
}

export class TtsClient {
  private ws: WebSocket | null = null;
  private player: TtsPlayer | null = null;
  private ready = false;
  private playerMime = 'audio/mpeg';
  private speechVoicesReady = false;
  private pendingSpeech: string[] = [];
  private voicesChangedHandler: (() => void) | null = null;
  private fallbackReason: string | null = null;
  private fallbackWatchTimer: number | null = null;
  private fallbackText: string | null = null;
  private fallbackUserActionListener: ((event: Event) => void) | null = null;
  private fallbackUserActionEvents: Array<keyof DocumentEventMap> = ['pointerdown', 'keydown'];

  constructor(private readonly baseUrl: string, private readonly sessionId: string) {}

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
      this.fallbackReason = null;
      this.fallbackText = null;
      this.updateFallbackState(null, false);
      this.clearFallbackWatchdog();
    };

    this.ws.onerror = (event) => {
      console.error('[tts] websocket error', event);
    };

    this.ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'tts_ready') {
            if (typeof payload.mime === 'string' && payload.mime) {
              this.playerMime = payload.mime;
              this.ensurePlayer(payload.mime);
            }
            this.ready = true;
            setTtsReady(true);
            setTtsMode('stream');
            setTtsError(null);
            console.info('[tts] stream ready', { mime: this.playerMime, sessionId: this.sessionId });
            return;
          }
          if (payload.type === 'tts_end') {
            this.player?.finalize();
            if (this.player && (this.player.isUsingMediaSource() || !this.player.isBlobPlaybackActive())) {
              this.player.prepare();
            }
            return;
          }
          if (payload.type === 'tts_error') {
            this.player?.cancel();
            if (this.player && (this.player.isUsingMediaSource() || !this.player.isBlobPlaybackActive())) {
              this.player.prepare();
            }
            const message =
              typeof payload.message === 'string' && payload.message ? payload.message : 'TTS 服务发生错误';
            this.ready = false;
            setTtsReady(false);
            setTtsMode('error');
            setTtsError(message);
            console.error('[tts] backend reported error', { message });
            return;
          }
          if (payload.type === 'tts_fallback') {
            const text = typeof payload.text === 'string' ? payload.text : '';
            const fallbackMessage =
              typeof payload.message === 'string' && payload.message
                ? payload.message
                : useSessionStore.getState().ttsError ?? 'TTS 流未就绪，已切换到浏览器语音播报。';
            this.ready = false;
            setTtsReady(false);
            console.warn('[tts] backend requested fallback, switching to browser speech', {
              reason: fallbackMessage,
              sessionId: this.sessionId,
            });
            this.speakFallback(text, fallbackMessage);
            return;
          }
        } catch (error) {
          console.warn('[tts] failed to parse control message', error);
        }
        return;
      }
      if (!this.ready) {
        // Drop audio chunks until the connection is acknowledged.
        return;
      }
      const chunk = event.data as ArrayBuffer;
      if (!this.player) {
        console.warn('[tts] received audio chunk without active player, dropping');
        return;
      }
      this.player.enqueue(chunk);
    };

    this.ws.onclose = (event) => {
      console.info('[tts] websocket closed', {
        sessionId: this.sessionId,
        code: event.code,
        reason: event.reason,
      });
      this.ready = false;
      setTtsReady(false);
      const { ttsMode } = useSessionStore.getState();
      if (ttsMode !== 'error' && ttsMode !== 'fallback') {
        setTtsMode('stream');
        setTtsError(null);
      }
      this.clearFallbackWatchdog();
    };
  }

  cancelPlayback() {
    this.player?.cancel();
    if (this.player && (this.player.isUsingMediaSource() || !this.player.isBlobPlaybackActive())) {
      this.player.prepare();
    }
    this.cancelSpeechFallback();
  }

  close() {
    this.cancelPlayback();
    this.ws?.close();
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
    this.player.prepare();
  }

  private speakFallback(text: string, reason?: string) {
    const fallbackReason = reason && reason.trim().length > 0 ? reason : '已切换到浏览器语音播报。';
    this.fallbackReason = fallbackReason;
    this.fallbackText = text || null;
    this.updateFallbackState(this.fallbackText, false);
    this.updateTtsMode('fallback', fallbackReason);
    this.ensureFallbackUserActionListener();
    if (!text) {
      console.debug('[tts] fallback invoked without text payload');
      return;
    }
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      console.error('[tts] browser does not support speech synthesis');
      this.updateTtsMode('error', '当前浏览器不支持语音合成，无法播放备用音频。');
      this.updateFallbackState(this.fallbackText, false);
      return;
    }
    const synth = window.speechSynthesis;
    const voices = synth.getVoices();
    console.debug('[tts] speech synthesis voice snapshot', {
      availableVoices: voices.length,
    });
    if (!this.speechVoicesReady && voices.length === 0) {
      this.pendingSpeech.push(text);
      this.ensureSpeechVoices();
      console.debug('[tts] queued fallback speech until voices load', { queueLength: this.pendingSpeech.length });
      return;
    }
    this.speechVoicesReady = true;
    try {
      synth.cancel();
      if (typeof synth.resume === 'function') {
        try {
          synth.resume();
        } catch (resumeError) {
          console.debug('[tts] resume call on speech synthesis failed', resumeError);
        }
      }
      const utterance = this.buildUtterance(text);
      console.info('[tts] speaking via browser speech synthesis', {
        textPreview: text.slice(0, 40),
        characters: text.length,
        voice: utterance.voice ? utterance.voice.name : 'default',
        sessionId: this.sessionId,
      });
      synth.speak(utterance);
      this.startFallbackWatchdog();
    } catch (error) {
      console.warn('[tts] browser speech synthesis failed', error);
      this.updateTtsMode('error', this.extractErrorMessage(error, '浏览器语音合成失败'));
      this.updateFallbackState(this.fallbackText, false);
    }
  }

  private ensureSpeechVoices() {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return;
    }
    if (this.speechVoicesReady) {
      return;
    }
    const synth = window.speechSynthesis;
    const voices = synth.getVoices();
    if (voices.length > 0) {
      this.speechVoicesReady = true;
      this.flushPendingSpeech();
      console.debug('[tts] speech synthesis voices became available (immediate)', {
        voices: voices.map((voice) => ({ name: voice.name, lang: voice.lang })),
      });
      return;
    }
    if (this.voicesChangedHandler) {
      return;
    }
    this.voicesChangedHandler = () => {
      this.speechVoicesReady = true;
      this.flushPendingSpeech();
      const available = synth.getVoices();
      console.debug('[tts] speech synthesis voices ready (event)', {
        voices: available.map((voice) => ({ name: voice.name, lang: voice.lang })),
      });
    };
    synth.addEventListener('voiceschanged', this.voicesChangedHandler, { once: true });
    // Trigger lazy voice loading on some browsers (e.g. Safari)
    synth.getVoices();
  }

  private flushPendingSpeech() {
    if (!this.speechVoicesReady || this.pendingSpeech.length === 0) {
      return;
    }
    const synth = window.speechSynthesis;
    const texts = this.pendingSpeech.splice(0);
    console.debug('[tts] flushing queued fallback speech', { count: texts.length });
    for (const text of texts) {
      try {
        synth.cancel();
        const utterance = this.buildUtterance(text);
        synth.speak(utterance);
        this.startFallbackWatchdog();
      } catch (error) {
        console.warn('[tts] browser speech synthesis failed', error);
        this.updateTtsMode('error', this.extractErrorMessage(error, '浏览器语音合成失败'));
        this.updateFallbackState(this.fallbackText, false);
      }
    }
  }

  private cancelSpeechFallback() {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return;
    }
    this.pendingSpeech = [];
    this.clearFallbackWatchdog();
    try {
      window.speechSynthesis.cancel();
    } catch (error) {
      console.warn('[tts] cancel speech synthesis failed', error);
    }
    this.fallbackText = null;
    this.updateFallbackState(null, false);
    this.teardownFallbackUserActionListener();
  }

  private teardownVoicesListener() {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return;
    }
    if (this.voicesChangedHandler) {
      try {
        window.speechSynthesis.removeEventListener('voiceschanged', this.voicesChangedHandler);
      } catch {
        // ignore
      }
      this.voicesChangedHandler = null;
    }
  }

  private updateTtsMode(mode: 'stream' | 'fallback' | 'error', error?: string | null) {
    const { setTtsMode, setTtsError } = useSessionStore.getState();
    setTtsMode(mode);
    if (error !== undefined) {
      setTtsError(error);
    }
  }

  private buildUtterance(text: string) {
    const utterance = new SpeechSynthesisUtterance(text);
    const synth = window.speechSynthesis;
    const voices = synth.getVoices();
    const preferredVoice = voices.find((voice) => voice.lang?.toLowerCase().startsWith('zh')) ?? voices[0];
    if (preferredVoice) {
      utterance.voice = preferredVoice;
      utterance.lang = preferredVoice.lang || 'zh-CN';
    } else {
      if (voices.length === 0) {
        console.warn('[tts] no speech synthesis voices available; relying on browser default');
      } else {
        console.warn('[tts] no Chinese voice available; using first voice as fallback', {
          fallbackVoice: voices[0]?.name,
        });
      }
      utterance.lang = 'zh-CN';
    }
    const startTimestamp = Date.now();
    utterance.onstart = () => {
      console.info('[tts] fallback speech started', {
        voice: preferredVoice ? preferredVoice.name : 'default',
        lang: utterance.lang,
        characters: text.length,
      });
      this.clearFallbackWatchdog();
      this.updateFallbackState(this.fallbackText, false);
      this.teardownFallbackUserActionListener();
    };
    utterance.onend = () => {
      console.info('[tts] fallback speech finished', {
        voice: preferredVoice ? preferredVoice.name : 'default',
        durationMs: Date.now() - startTimestamp,
      });
      this.updateTtsMode('fallback', this.fallbackReason);
      this.clearFallbackWatchdog();
      this.updateFallbackState(this.fallbackText, false);
      this.teardownFallbackUserActionListener();
    };
    utterance.onerror = (event) => {
      const errorMessage =
        (event.error && typeof event.error === 'string'
          ? `浏览器语音合成失败：${event.error}`
          : this.fallbackReason) || '浏览器语音合成失败';
      console.error('[tts] fallback speech error', event);
      this.updateTtsMode('error', errorMessage);
      this.clearFallbackWatchdog();
      this.updateFallbackState(this.fallbackText, false);
    };
    utterance.onpause = () => {
      console.debug('[tts] fallback speech paused');
    };
    utterance.onresume = () => {
      console.debug('[tts] fallback speech resumed');
    };
    return utterance;
  }

  private startFallbackWatchdog() {
    if (typeof window === 'undefined') {
      return;
    }
    if (this.fallbackWatchTimer !== null) {
      window.clearTimeout(this.fallbackWatchTimer);
    }
    this.fallbackWatchTimer = window.setTimeout(() => {
      if (!window.speechSynthesis.speaking) {
        const message =
          this.fallbackReason ?? '浏览器尚未开始朗读，请点击页面任意位置后重试。';
        console.warn('[tts] speech synthesis has not started within expected window', {
          pending: window.speechSynthesis.pending,
          speaking: window.speechSynthesis.speaking,
          sessionId: this.sessionId,
        });
        this.fallbackReason = message;
        this.updateTtsMode('fallback', message);
        this.updateFallbackState(this.fallbackText, true);
        this.ensureFallbackUserActionListener();
      }
    }, 3000);
  }

  private clearFallbackWatchdog() {
    if (this.fallbackWatchTimer !== null) {
      window.clearTimeout(this.fallbackWatchTimer);
      this.fallbackWatchTimer = null;
    }
  }

  private updateFallbackState(text: string | null, needUserAction: boolean) {
    const { setTtsFallbackText, setTtsFallbackNeedUserAction } = useSessionStore.getState();
    setTtsFallbackText(text);
    setTtsFallbackNeedUserAction(needUserAction);
  }

  retryFallbackSpeech() {
    if (!this.fallbackText) {
      console.warn('[tts] manual fallback retry requested but no text available');
      this.updateFallbackState(null, false);
      return;
    }
    console.info('[tts] manual fallback retry triggered');
    this.updateFallbackState(this.fallbackText, false);
    this.speakFallback(this.fallbackText, this.fallbackReason ?? undefined);
  }

  private ensureFallbackUserActionListener() {
    if (typeof document === 'undefined') {
      return;
    }
    if (!this.fallbackText) {
      return;
    }
    if (this.fallbackUserActionListener) {
      return;
    }
    const handler = () => {
      console.info('[tts] detected user interaction, retrying fallback speech');
      this.teardownFallbackUserActionListener();
      this.retryFallbackSpeech();
    };
    this.fallbackUserActionListener = handler;
    for (const eventName of this.fallbackUserActionEvents) {
      document.addEventListener(eventName, handler, { once: true });
    }
  }

  private teardownFallbackUserActionListener() {
    if (typeof document === 'undefined') {
      return;
    }
    if (!this.fallbackUserActionListener) {
      return;
    }
    for (const eventName of this.fallbackUserActionEvents) {
      document.removeEventListener(eventName, this.fallbackUserActionListener);
    }
    this.fallbackUserActionListener = null;
  }

  private extractErrorMessage(error: unknown, fallback: string) {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    if (typeof error === 'string' && error) {
      return error;
    }
    return fallback;
  }
}
import ReconnectingWebSocket from 'reconnecting-websocket';
import { useSessionStore } from '../store/useSessionStore';

const WS_OPTIONS = { maxReconnectionDelay: 4000, minReconnectionDelay: 250, reconnectionDelayGrowFactor: 1.5 };

export class AsrClient {
  private socket: ReconnectingWebSocket | null = null;
  private isStreaming = false;

  constructor(private readonly baseUrl: string, private readonly sessionId: string) {}

  connect() {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/asr?session=${this.sessionId}`;
    this.socket = new ReconnectingWebSocket(wsUrl, [], WS_OPTIONS);
    this.socket.addEventListener('open', () => {
      console.info('[asr] websocket connected');
    });
    this.socket.addEventListener('close', (event) => {
      console.warn('[asr] websocket closed', event.code, event.reason);
      this.isStreaming = false;
    });
    this.socket.addEventListener('message', (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'asr_final') {
        useSessionStore.getState().addTranscript({ speaker: 'user', text: data.text });
        console.info('[asr] final transcript', data.text);
        return;
      }
      if (data.type === 'asr_partial') {
        console.debug('[asr] partial transcript', data.text);
        return;
      }
      if (data.type === 'asr_error') {
        console.error('[asr] backend error', data.message);
        const store = useSessionStore.getState();
        store.setMicStatus('error');
        store.setMicError(data.message ?? '识别失败');
        this.isStreaming = false;
        return;
      }
      if (data.type === 'asr_stopped') {
        console.info('[asr] backend confirmed stop');
        this.isStreaming = false;
        useSessionStore.getState().setMicStatus('idle');
        return;
      }
      if (data.type === 'asr_handshake') {
        console.info('[asr] handshake payload', data.payload);
      }
    });
  }

  sendText(text: string) {
    this.socket?.send(text);
  }

  startStreaming(sampleRate: number, language: string) {
    if (!this.socket) {
      console.warn('[asr] cannot start streaming before socket initialises');
      return;
    }
    const payload = { type: 'start', sampleRate, language };
    console.info('[asr] sending start control', payload);
    this.socket.send(JSON.stringify(payload));
    this.isStreaming = true;
  }

  sendAudioChunk(chunk: ArrayBuffer) {
    if (!this.socket) {
      console.warn('[asr] dropping audio chunk because socket is null');
      return;
    }
    if (!this.isStreaming) {
      console.warn('[asr] dropping audio chunk because stream not started');
      return;
    }
    this.socket.send(chunk);
  }

  stopStreaming() {
    if (!this.socket || !this.isStreaming) {
      return;
    }
    console.info('[asr] sending stop control');
    this.socket.send(JSON.stringify({ type: 'stop' }));
    this.isStreaming = false;
  }

  close() {
    this.socket?.close();
    this.isStreaming = false;
  }
}

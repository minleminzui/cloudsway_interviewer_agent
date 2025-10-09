// frontend/src/api/asrClient.ts
import ReconnectingWebSocket from 'reconnecting-websocket';
import { useSessionStore } from '../store/useSessionStore';

const WS_OPTIONS = {
  maxReconnectionDelay: 4000,
  minReconnectionDelay: 250,
  reconnectionDelayGrowFactor: 1.5,
};

export class AsrClient {
  private socket: ReconnectingWebSocket | null = null;
  private isStreaming = false;
  private lastStartPayload: any = null;
  private heartbeatTimer: any = null;

  constructor(public baseUrl: string, public sessionId: string) {}

  connect() {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/asr?session=${this.sessionId}`;
    this.socket = new ReconnectingWebSocket(wsUrl, [], WS_OPTIONS);

    // ✨ 确保底层以 ArrayBuffer 发送二进制
    (this.socket as any).binaryType = 'arraybuffer';

    this.socket.addEventListener('open', () => {
      console.info('[asr] websocket connected');
      if (this.isStreaming && this.lastStartPayload) {
        console.info('[asr] restoring stream after reconnect');
        this._sendJSON(this.lastStartPayload);
      }
      this._startHeartbeat();
    });

    this.socket.addEventListener('close', (event) => {
      console.warn('[asr] websocket closed', event.code, event.reason);
      this.isStreaming = false;
      this._stopHeartbeat();
    });

    this.socket.addEventListener('message', (event) => {
      this._handleMessage(event.data);
    });
  }

  private _handleMessage(raw: any) {
    let data: any;
    try {
      data = JSON.parse(raw);
    } catch {
      // 忽略纯二进制
      return;
    }

    const store = useSessionStore.getState();
    switch (data.type) {
      case 'asr_handshake':
        console.info('[asr] handshake payload', data.payload);
        break;
      case 'asr_partial':
        // 可在 UI 顶部做“正在听写：xxx”的回显（看你 store 的结构，这里简单打印）
        console.debug('[asr] partial transcript', data.text);
        break;
      case 'asr_final':
        store.addTranscript({ speaker: 'user', text: data.text });
        console.info('[asr] final transcript', data.text);
        break;
      case 'asr_error':
        console.error('[asr] backend error', data.message);
        store.setMicStatus('error');
        store.setMicError(data.message ?? '识别失败');
        this.isStreaming = false;
        break;
      case 'asr_stopped':
        console.info('[asr] backend confirmed stop');
        this.isStreaming = false;
        store.setMicStatus('idle');
        break;
      default:
        console.debug('[asr] unknown message type', data);
    }
  }

  private async _sendWhenReady(data: string | ArrayBuffer) {
    if (!this.socket) return;
  
    // 用浏览器 WebSocket 的签名做一次断言，避免 ReconnectingWebSocket 的 Node 类型约束
    const sock = this.socket as unknown as WebSocket;
  
    if (sock.readyState === WebSocket.OPEN) {
      sock.send(data);
    } else {
      await new Promise<void>((resolve) => {
        const onOpen = () => {
          this.socket?.removeEventListener('open', onOpen);
          resolve();
        };
        this.socket?.addEventListener('open', onOpen);
      });
      (this.socket as unknown as WebSocket).send(data);
    }
  }
  
  private _sendJSON(obj: any) {
    void this._sendWhenReady(JSON.stringify(obj));
  }

  sendText(text: string) {
    this._sendJSON({ type: 'text', text });
  }

  startStreaming(sampleRate: number, language: string) {
    if (!this.socket) {
      console.warn('[asr] cannot start streaming before socket initialises');
      return;
    }
    const payload = { type: 'start', sampleRate, language };
    this.lastStartPayload = payload;
    this.isStreaming = true;
    console.info('[asr] sending start control', payload);
    this._sendJSON(payload);
  }

  sendAudioChunk(chunk: ArrayBuffer) {
    if (!this.socket || !this.isStreaming) return;
    this._sendWhenReady(chunk);
  }

  stopStreaming() {
    if (!this.socket || !this.isStreaming) return;
    console.info('[asr] sending stop control');
    this._sendJSON({ type: 'stop' });
    this.isStreaming = false;
  }

  private _startHeartbeat() {
    this._stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this._sendJSON({ type: 'ping' });
      }
    }, 5000);
  }

  private _stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  close() {
    this._stopHeartbeat();
    this.socket?.close();
    this.isStreaming = false;
  }
}

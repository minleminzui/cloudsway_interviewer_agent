import ReconnectingWebSocket from 'reconnecting-websocket';
import { useSessionStore } from '../store/useSessionStore';

const WS_OPTIONS = { maxReconnectionDelay: 4000, minReconnectionDelay: 250, reconnectionDelayGrowFactor: 1.5 };

export class AsrClient {
  private socket: ReconnectingWebSocket | null = null;

  constructor(private readonly baseUrl: string, private readonly sessionId: string) {}

  connect() {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/asr?session=${this.sessionId}`;
    this.socket = new ReconnectingWebSocket(wsUrl, [], WS_OPTIONS);
    this.socket.addEventListener('message', (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'asr_final') {
        useSessionStore.getState().addTranscript({ speaker: 'user', text: data.text });
      }
    });
  }

  sendText(text: string) {
    this.socket?.send(text);
  }

  close() {
    this.socket?.close();
  }
}

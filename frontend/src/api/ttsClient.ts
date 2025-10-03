import { TtsPlayer } from '../audio/TtsPlayer';
import { useSessionStore } from '../store/useSessionStore';

function makeWsUrl(baseUrl: string, path: string) {
  const url = new URL(path, baseUrl);
  url.protocol = url.protocol.replace('http', 'ws');
  return url.toString();
}

export class TtsClient {
  private ws: WebSocket | null = null;
  private player = new TtsPlayer();
  private ready = false;

  constructor(private readonly baseUrl: string, private readonly sessionId: string) {}

  connect() {
    this.player.prepare();
    const wsUrl = makeWsUrl(this.baseUrl, `/ws/tts?session=${this.sessionId}`);
    this.ws = new WebSocket(wsUrl);
    this.ws.binaryType = 'arraybuffer';
    const setTtsReady = useSessionStore.getState().setTtsReady;

    this.ws.onopen = () => {
      this.ready = false;
      setTtsReady(false);
    };

    this.ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'tts_ready') {
            this.ready = true;
            setTtsReady(true);
            return;
          }
          if (payload.type === 'tts_end') {
            this.player.finalize();
            this.player.prepare();
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
      this.player.enqueue(chunk);
    };

    this.ws.onclose = () => {
      this.ready = false;
      setTtsReady(false);
    };
  }

  cancelPlayback() {
    this.player.cancel();
    this.player.prepare();
  }

  close() {
    this.cancelPlayback();
    this.ws?.close();
    this.ws = null;
    this.player.destroy();
  }
}

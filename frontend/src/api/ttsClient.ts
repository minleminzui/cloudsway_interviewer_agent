import ReconnectingWebSocket from 'reconnecting-websocket';

const WS_OPTIONS = { maxReconnectionDelay: 4000, minReconnectionDelay: 250, reconnectionDelayGrowFactor: 1.5 };

export class TtsClient {
  private socket: ReconnectingWebSocket | null = null;
  private audioContext: AudioContext;
  private bufferQueue: Float32Array[] = [];
  private playing = false;

  constructor(private readonly baseUrl: string, private readonly sessionId: string) {
    this.audioContext = new AudioContext({ sampleRate: 16000 });
  }

  connect() {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/tts?session=${this.sessionId}`;
    this.socket = new ReconnectingWebSocket(wsUrl, [], WS_OPTIONS);
    this.socket.addEventListener('message', async (event) => {
      if (typeof event.data === 'string') {
        const payload = JSON.parse(event.data);
        if (payload.type === 'tts_end') {
          return;
        }
      } else {
        const arrayBuffer = await event.data.arrayBuffer();
        const pcmView = new DataView(arrayBuffer);
        const floatData = new Float32Array(pcmView.byteLength / 2);
        for (let i = 0; i < floatData.length; i++) {
          floatData[i] = pcmView.getInt16(i * 2, true) / 32767;
        }
        this.bufferQueue.push(floatData);
        if (!this.playing) {
          this.playing = true;
          this.flush();
        }
      }
    });
  }

  private async flush() {
    while (this.bufferQueue.length > 0) {
      const chunk = this.bufferQueue.shift();
      if (!chunk) continue;
      const audioBuffer = this.audioContext.createBuffer(1, chunk.length, 16000);
      audioBuffer.getChannelData(0).set(chunk);
      const source = this.audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.audioContext.destination);
      source.start();
      await new Promise((resolve) => (source.onended = resolve));
    }
    this.playing = false;
  }

  close() {
    this.socket?.close();
    this.audioContext.close();
  }
}

// frontend/src/api/agentClient.ts
import ReconnectingWebSocket from 'reconnecting-websocket';
import { useSessionStore } from '../store/useSessionStore';

const WS_OPTIONS = {
  maxReconnectionDelay: 4000,
  minReconnectionDelay: 250,
  reconnectionDelayGrowFactor: 1.5,
};

export class AgentClient {
  private socket: ReconnectingWebSocket | null = null;

  constructor(
    public baseUrl: string,
    public sessionId: string,
    public topic: string
  ) {}

  connect() {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/agent?session=${this.sessionId}&topic=${encodeURIComponent(
      this.topic
    )}`;
    this.socket = new ReconnectingWebSocket(wsUrl, [], WS_OPTIONS);
    const store = useSessionStore.getState();

    this.socket.addEventListener('message', (event) => {
      try {
        // ✅ 1. 跳过二进制帧
        if (event.data instanceof Blob || event.data instanceof ArrayBuffer) {
          console.debug('[agentClient] binary message ignored');
          return;
        }

        // ✅ 2. 尝试解析 JSON
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'outline': {
            const outlineSections = data.payload.sections.map((section: any) => ({
              stage: section.stage,
              questions: section.questions.map((q: any) => q.question),
            }));
            store.setOutline(outlineSections);
            break;
          }

          case 'policy': {
            store.addTranscript({ speaker: 'agent', text: data.question });
            store.setPendingQuestion(data.question);
            store.setStage(data.stage);
            store.updateNotes(
              data.notes.map((item: any) => ({
                category: item.category,
                content: item.content,
                requiresClarification: item.requires_clarification,
                confidence: item.confidence,
              }))
            );
            break;
          }

          case 'agent_reply': {
            store.addTranscript({ speaker: 'agent', text: data.text });
            store.setPendingQuestion(data.text);
            store.setStage(data.stage);
            break;
          }

          case 'agent_ack':
            console.info('[agentClient] ack:', data.text);
            break;

          default:
            console.debug('[agentClient] unhandled message', data);
        }
      } catch (err) {
        console.error('[agentClient] parse error', err, event.data);
      }
    });
  }

  sendUserTurn(text: string) {
    if (!this.socket) return;
    this.socket.send(JSON.stringify({ type: 'user_turn', text }));
  }

  close() {
    this.socket?.close();
  }
}

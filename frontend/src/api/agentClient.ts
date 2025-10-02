import ReconnectingWebSocket from 'reconnecting-websocket';
import { useSessionStore } from '../store/useSessionStore';

const WS_OPTIONS = { maxReconnectionDelay: 4000, minReconnectionDelay: 250, reconnectionDelayGrowFactor: 1.5 };

export class AgentClient {
  private socket: ReconnectingWebSocket | null = null;

  constructor(private readonly baseUrl: string, private readonly sessionId: string, private readonly topic: string) {}

  connect() {
    const wsUrl = `${this.baseUrl.replace('http', 'ws')}/ws/agent?session=${this.sessionId}&topic=${encodeURIComponent(this.topic)}`;
    this.socket = new ReconnectingWebSocket(wsUrl, [], WS_OPTIONS);
    this.socket.addEventListener('message', (event) => {
      const data = JSON.parse(event.data);
      const store = useSessionStore.getState();
      if (data.type === 'outline') {
        const outlineSections = data.payload.sections.map((section: any) => ({
          stage: section.stage,
          questions: section.questions.map((q: any) => q.question)
        }));
        store.setOutline(outlineSections);
      }
      if (data.type === 'policy') {
        store.addTranscript({ speaker: 'agent', text: data.question });
        store.setPendingQuestion(data.question);
        store.setStage(data.stage);
        store.updateNotes(
          data.notes.map((item: any) => ({
            category: item.category,
            content: item.content,
            requiresClarification: item.requires_clarification
          }))
        );
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

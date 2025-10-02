import { useEffect, useRef } from 'react';
import { AgentClient } from '../api/agentClient';
import { AsrClient } from '../api/asrClient';
import { TtsClient } from '../api/ttsClient';
import { useSessionStore } from '../store/useSessionStore';

export function useInterviewClients(apiBaseUrl: string) {
  const session = useSessionStore((state) => ({ sessionId: state.sessionId, topic: state.topic }));
  const agentRef = useRef<AgentClient | null>(null);
  const asrRef = useRef<AsrClient | null>(null);
  const ttsRef = useRef<TtsClient | null>(null);

  useEffect(() => {
    if (session.sessionId === '0') {
      return;
    }
    agentRef.current = new AgentClient(apiBaseUrl, session.sessionId, session.topic);
    asrRef.current = new AsrClient(apiBaseUrl, session.sessionId);
    ttsRef.current = new TtsClient(apiBaseUrl, session.sessionId);
    agentRef.current.connect();
    asrRef.current.connect();
    ttsRef.current.connect();
    return () => {
      agentRef.current?.close();
      asrRef.current?.close();
      ttsRef.current?.close();
    };
  }, [apiBaseUrl, session.sessionId, session.topic]);

  return {
    sendUserUtterance(text: string) {
      if (session.sessionId === '0') {
        return;
      }
      agentRef.current?.sendUserTurn(text);
      asrRef.current?.sendText(text);
    }
  };
}

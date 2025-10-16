// frontend/src/hooks/useInterviewClients.ts
import { useCallback, useEffect, useRef } from 'react';
import { AgentClient } from '../api/agentClient';
import { AsrClient } from '../api/asrClient';
import { TtsClient } from '../api/ttsClient';
import { useSessionStore } from '../store/useSessionStore';
import { MicRecorder } from '../audio/MicRecorder';

export function useInterviewClients(apiBaseUrl: string) {
  const session = useSessionStore((state) => ({
    sessionId: state.sessionId,
    topic: state.topic,
  }));
  const micStatus = useSessionStore((state) => state.micStatus);
  const micError = useSessionStore((state) => state.micError);
  const setMicStatus = useSessionStore((state) => state.setMicStatus);
  const setMicError = useSessionStore((state) => state.setMicError);
  const setTtsFallbackRetry = useSessionStore((state) => state.setTtsFallbackRetry);

  const agentRef = useRef<AgentClient | null>(null);
  const asrRef = useRef<AsrClient | null>(null);
  const ttsRef = useRef<TtsClient | null>(null);
  const micRef = useRef<MicRecorder | null>(null);
  const pendingStopRef = useRef(false);

  useEffect(() => {
    const sid = session.sessionId;
    const topic = session.topic;

    if (!sid || sid === '0') {
      console.info('[session] waiting for valid sessionId...');
      return;
    }

    if (
      agentRef.current?.sessionId === sid &&
      asrRef.current?.sessionId === sid &&
      ttsRef.current?.sessionId === sid
    ) {
      console.info('[session] skip duplicate init for sid=', sid);
      return;
    }

    console.info('[session] init clients', { sid, topic });

    agentRef.current?.close?.();
    asrRef.current?.close?.();
    ttsRef.current?.close?.();

    const agent = new AgentClient(apiBaseUrl, sid, topic);
    // 🔗 关键：asr 识别完成后 => 立刻发给 agent
    const asr = new AsrClient(apiBaseUrl, sid, {
      onFinal: (text) => {
        agentRef.current?.sendUserTurn(text);
      },
      onPartial: (text) => {
        const store = useSessionStore.getState();
        store.setAsrPartial?.(text);
      },
    });
    asrRef.current = asr;

    const tts = new TtsClient(apiBaseUrl, sid);

    (agent as any).sessionId = sid;
    (asr as any).sessionId = sid;
    (tts as any).sessionId = sid;

    agentRef.current = agent;
    asrRef.current = asr;
    ttsRef.current = tts;    

    (async () => {
      try {
        await Promise.all([tts.connect(), asr.connect(), agent.connect()]);
        console.info('[clients] ✅ all websocket connections started for sid', sid);
      } catch (err) {
        console.error('[clients] ❌ websocket connection error', err);
      }
    })();

    setTtsFallbackRetry(() => () => ttsRef.current?.retryFallbackSpeech());

    return () => {
      console.info(`[session] cleanup sid=${sid}`);
      micRef.current?.stop();
      agent.close();
      asr.close();
      tts.close();
      asrRef.current?.close();
      setTtsFallbackRetry(null);
    };
  }, [apiBaseUrl, session.sessionId, session.topic, setTtsFallbackRetry]);

  const stopMicrophone = useCallback(() => {
    if (!micRef.current || pendingStopRef.current) return;
    pendingStopRef.current = true;
    console.info('[mic] stop requested by UI');
    try {
      micRef.current.stop();
      asrRef.current?.stopStreaming();
      const store = useSessionStore.getState();
      if (store.micStatus !== 'error') setMicError(null);
    } finally {
      pendingStopRef.current = false;
    }
  }, [setMicError]);

  const startMicrophone = useCallback(async () => {
    if (session.sessionId === '0') {
      setMicError('请先创建会话');
      setMicStatus('error');
      return;
    }
    if (!asrRef.current) {
      setMicError('ASR 客户端未就绪');
      setMicStatus('error');
      return;
    }
    if (micStatus === 'starting' || micStatus === 'recording') return;

    if (!micRef.current) micRef.current = new MicRecorder();
    setMicError(null);

    try {
      if (!micRef.current) micRef.current = new MicRecorder();
      await micRef.current.start({
        onReady: async ({ sampleRate }) => {
          console.info('[mic] ready, starting ASR stream', sampleRate);
          asrRef.current?.startStreaming(sampleRate, 'zh-CN');
        },
        onChunk: (chunk) => {
          asrRef.current?.sendAudioChunk(chunk);
        },
        onStop: (previewUrl?: string) => {
          console.info('[mic] stopped callback');
          asrRef.current?.stopStreaming();
          if (previewUrl) {
            const store = useSessionStore.getState();
            store.addTranscript?.({ speaker: 'user', text: '[语音]', audioUrl: previewUrl });
          }
        },
      });
    } catch (err) {
      console.error('[mic] start failed', err);
      setMicError('无法访问麦克风');
      setMicStatus('error');
    }
  }, [micStatus, session.sessionId, setMicError, setMicStatus]);

  return {
    sendUserUtterance(text: string) {
      if (session.sessionId === '0') return;
      agentRef.current?.sendUserTurn(text);
      asrRef.current?.sendText(text);
    },
    startMicrophone,
    stopMicrophone,
    micStatus,
    micError,
  };
}

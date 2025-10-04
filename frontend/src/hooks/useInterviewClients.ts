import { useCallback, useEffect, useRef } from 'react';
import { AgentClient } from '../api/agentClient';
import { AsrClient } from '../api/asrClient';
import { TtsClient } from '../api/ttsClient';
import { useSessionStore } from '../store/useSessionStore';
import { MicRecorder } from '../audio/MicRecorder';

export function useInterviewClients(apiBaseUrl: string) {
  const session = useSessionStore((state) => ({ sessionId: state.sessionId, topic: state.topic }));
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
    if (session.sessionId === '0') {
      setTtsFallbackRetry(null);
      if (micRef.current) {
        micRef.current.stop();
        micRef.current = null;
      }
      return;
    }
    agentRef.current = new AgentClient(apiBaseUrl, session.sessionId, session.topic);
    asrRef.current = new AsrClient(apiBaseUrl, session.sessionId);
    ttsRef.current = new TtsClient(apiBaseUrl, session.sessionId);
    agentRef.current.connect();
    asrRef.current.connect();
    ttsRef.current.connect();
    setTtsFallbackRetry(() => () => ttsRef.current?.retryFallbackSpeech());
    return () => {
      if (micRef.current) {
        micRef.current.stop();
        micRef.current = null;
      }
      agentRef.current?.close();
      asrRef.current?.close();
      ttsRef.current?.close();
      setTtsFallbackRetry(null);
    };
  }, [apiBaseUrl, session.sessionId, session.topic, setTtsFallbackRetry]);

  const stopMicrophone = useCallback(() => {
    if (!micRef.current || pendingStopRef.current) {
      return;
    }
    pendingStopRef.current = true;
    console.info('[mic] stop requested by UI');
    try {
      micRef.current.stop();
      asrRef.current?.stopStreaming();
      const store = useSessionStore.getState();
      if (store.micStatus !== 'error') {
        setMicError(null);
      }
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
    if (micStatus === 'starting' || micStatus === 'recording') {
      console.info('[mic] start requested while already active');
      return;
    }
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      setMicStatus('error');
      setMicError('浏览器不支持麦克风');
      return;
    }
    if (!micRef.current) {
      micRef.current = new MicRecorder();
    }
    setMicError(null);
    try {
      await micRef.current.start({
        onReady: async ({ sampleRate }) => {
          console.info('[mic] ready, preparing ASR stream', { sampleRate });
          asrRef.current?.startStreaming(sampleRate, 'zh-CN');
        },
        onChunk: (chunk) => {
          asrRef.current?.sendAudioChunk(chunk);
        },
        onStop: () => {
          console.info('[mic] recorder stopped callback');
          asrRef.current?.stopStreaming();
        }
      });
    } catch (error) {
      console.error('[mic] failed to start microphone', error);
    }
  }, [micStatus, session.sessionId, setMicError, setMicStatus]);

  return {
    sendUserUtterance(text: string) {
      if (session.sessionId === '0') {
        return;
      }
      agentRef.current?.sendUserTurn(text);
      asrRef.current?.sendText(text);
    },
    startMicrophone,
    stopMicrophone,
    micStatus,
    micError
  };
}

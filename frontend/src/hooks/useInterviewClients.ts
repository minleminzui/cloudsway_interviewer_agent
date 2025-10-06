// src/hooks/useInterviewClients.ts
import { useCallback, useEffect, useRef } from 'react';
import { AgentClient } from '../api/agentClient';
import { AsrClient } from '../api/asrClient';
import { TtsClient } from '../api/ttsClient';
import { useSessionStore } from '../store/useSessionStore';
import { MicRecorder } from '../audio/MicRecorder';

/**
 * 管理语音面试过程中的主要客户端：
 * Agent（智能体）、ASR（语音识别）、TTS（语音合成）、Mic（麦克风录制）
 */
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

  // === 初始化或切换 session 时重建所有客户端 ===
  useEffect(() => {
    if (session.sessionId === '0') {
      console.info('[session] cleanup: sessionId=0');
      setTtsFallbackRetry(null);
      if (micRef.current) {
        micRef.current.stop();
        micRef.current = null;
      }
      return;
    }

    const currentSession = session.sessionId;
    console.info('[session] initializing interview clients', session);

    // 防止旧连接未关闭
    agentRef.current?.close?.();
    asrRef.current?.close?.();
    ttsRef.current?.close?.();

    // === 创建新客户端 ===
    const agent = new AgentClient(apiBaseUrl, currentSession, session.topic);
    const asr = new AsrClient(apiBaseUrl, currentSession);
    const tts = new TtsClient(apiBaseUrl, currentSession);
    console.info('[interview] init clients', session);

    agentRef.current = agent;
    asrRef.current = asr;
    ttsRef.current = tts;

    // === 建立 WebSocket ===
    try {
      agent.connect();
      asr.connect();
      tts.connect();
      console.info('[clients] all websocket connections started');
    } catch (err) {
      console.error('[clients] failed to connect websockets', err);
    }

    setTtsFallbackRetry(() => () => ttsRef.current?.retryFallbackSpeech());

    // === 清理逻辑 ===
    return () => {
      const sidToClose = currentSession;
      console.info(`[session] cleaning up interview clients for sid=${sidToClose}`);

      setTimeout(() => {
        // ✅ 使用 TtsClient 公有方法 getSessionId() 来避免访问 private
        const currentTtsId = ttsRef.current?.getSessionId?.();
        if (currentTtsId === sidToClose) {
          try {
            micRef.current?.stop?.();
            agentRef.current?.close?.();
            asrRef.current?.close?.();
            ttsRef.current?.close?.();
            setTtsFallbackRetry(null);
            console.info(`[session] closed all ws for sid=${sidToClose}`);
          } catch (e) {
            console.warn(`[session] cleanup error for sid=${sidToClose}`, e);
          }
        } else {
          console.debug(`[session] skip cleanup (current=${currentTtsId}, old=${sidToClose})`);
        }
      }, 1000);
    };
  }, [apiBaseUrl, session.sessionId, session.topic, setTtsFallbackRetry]);

  // === 停止麦克风 ===
  const stopMicrophone = useCallback(() => {
    if (!micRef.current || pendingStopRef.current) return;
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

  // === 启动麦克风 ===
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
        },
      });
    } catch (error) {
      console.error('[mic] failed to start microphone', error);
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

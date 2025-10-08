// frontend/src/pages/TtsDemoPage.tsx
import { useEffect, useRef, useState } from 'react';
import { TtsClient } from '../api/ttsClient';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export function TtsDemoPage() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const clientRef = useRef<TtsClient | null>(null);

  useEffect(() => {
    const client = new TtsClient(API_BASE_URL, sessionId);
    client.connect();
    clientRef.current = client;
    return () => client.close();
  }, [sessionId]);

  async function startDemo() {
    await fetch(`${API_BASE_URL}/v1/tts/demo/start?session=${sessionId}`, {
      method: 'POST'
    });
  }

  async function stopDemo() {
    await fetch(`${API_BASE_URL}/v1/tts/demo/stop?session=${sessionId}`, {
      method: 'POST'
    });
    clientRef.current?.cancelPlayback();
  }

  return (
    <div className="layout" style={{ padding: '2rem' }}>
      <h1>流式 TTS 播放调试</h1>
      <p>使用 demo WebM 资源验证 /ws/tts 播放与打断逻辑。</p>
      <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
        <button onClick={startDemo}>开始播放</button>
        <button onClick={() => clientRef.current?.cancelPlayback()}>Barge-in 打断</button>
        <button onClick={stopDemo}>停止</button>
      </div>
    </div>
  );
}

export default TtsDemoPage;

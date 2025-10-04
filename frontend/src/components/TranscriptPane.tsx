import { useEffect, useRef } from 'react';
import { useSessionStore } from '../store/useSessionStore';

export function TranscriptPane() {
  const transcript = useSessionStore((state) => state.transcript);
  const ttsReady = useSessionStore((state) => state.ttsReady);
  const ttsMode = useSessionStore((state) => state.ttsMode);
  const ttsError = useSessionStore((state) => state.ttsError);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcript]);

  let banner: { type: 'waiting' | 'fallback' | 'error'; message: string } | null = null;
  if (ttsMode === 'error') {
    banner = {
      type: 'error',
      message: `语音播报失败：${ttsError || '请检查语音配置或稍后重试。'}`
    };
  } else if (ttsMode === 'fallback') {
    banner = {
      type: 'fallback',
      message: '云端语音不可用，已切换到浏览器语音合成。'
    };
  } else if (!ttsReady) {
    banner = {
      type: 'waiting',
      message: '语音播报连接中，请稍候…'
    };
  }

  return (
    <div className="panel transcript" ref={scrollRef}>
      <h2>实时记录</h2>
      {banner ? <div className={`tts-banner ${banner.type}`}>{banner.message}</div> : null}
      <ul>
        {transcript.map((entry, index) => (
          <li key={`${entry.speaker}-${index}`} className={entry.speaker}>
            <span className="speaker">{entry.speaker === 'agent' ? '采访官' : '受访者'}</span>
            <span className="text">{entry.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

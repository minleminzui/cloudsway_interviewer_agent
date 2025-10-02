import { useEffect, useRef } from 'react';
import { useSessionStore } from '../store/useSessionStore';

export function TranscriptPane() {
  const transcript = useSessionStore((state) => state.transcript);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcript]);

  return (
    <div className="panel transcript" ref={scrollRef}>
      <h2>实时记录</h2>
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

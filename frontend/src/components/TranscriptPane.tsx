// frontend/src/pages/MainConsole.tsx
import '../App.css';
import { useSessionStore } from '../store/useSessionStore';

function sec(ms?: number) {
  if (!ms) return '';
  const s = Math.round(ms / 1000);
  return ` · ${s}s`;
}

export default function TranscriptPane() {
  const transcript = useSessionStore((s) => s.transcript);

  return (
    <div className="transcript-pane">
      {transcript.map((m, i) => (
        <div key={i} className={`msg ${m.speaker}`}>
          {m.audioUrl ? (
            <div className="bubble audio">
              <div className="meta">
                {m.speaker === 'user' ? '受访者' : '采访官'} [语音]
                {sec(m.durationMs)}
              </div>
              <audio controls src={m.audioUrl} preload="metadata" style={{ width: '100%' }} />
            </div>
          ) : (
            <div className="bubble text">
              <div className="meta">{m.speaker === 'user' ? '受访者' : '采访官'}</div>
              <p>{m.text}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
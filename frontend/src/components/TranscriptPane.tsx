import { useSessionStore } from '../store/useSessionStore';

function TranscriptPane() {
  const items = useSessionStore((s) => s.transcript);
  const asrPartial = useSessionStore((s) => s.asrPartial);

  return (
    <div className="transcript">
      {items.map((m, i) => (
        <div key={i} className={`bubble ${m.speaker}`}>
          {m.audioUrl && <audio controls src={m.audioUrl} style={{ width: '100%' }} />}
          {m.text && <p>{m.text}</p>}
        </div>
      ))}
      {!!asrPartial && (
        <div className="bubble user partial" style={{ opacity: 0.7 }}>
          （识别中）{asrPartial}
        </div>
      )}
    </div>
  );
}

export default TranscriptPane;

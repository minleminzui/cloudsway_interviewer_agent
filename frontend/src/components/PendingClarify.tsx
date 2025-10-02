import { useSessionStore } from '../store/useSessionStore';

export function PendingClarify() {
  const notes = useSessionStore((state) => state.notes);
  const pending = notes.filter((note) => note.requiresClarification);

  return (
    <div className="panel">
      <h2>待澄清</h2>
      {pending.length === 0 ? <p className="empty">暂无待处理条目</p> : null}
      <ul>
        {pending.map((note, index) => (
          <li key={`${note.content}-${index}`}>{note.content}</li>
        ))}
      </ul>
    </div>
  );
}

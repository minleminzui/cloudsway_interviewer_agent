import { useMemo } from 'react';
import { useSessionStore } from '../store/useSessionStore';

export function OutlinePanel() {
  const outline = useSessionStore((state) => state.outline);
  const transcript = useSessionStore((state) => state.transcript);

  const totalQuestions = useMemo(
    () => outline.reduce((acc, section) => acc + section.questions.length, 0),
    [outline]
  );
  const answeredCount = useMemo(() => transcript.filter((item) => item.speaker === 'agent').length, [transcript]);
  const coverage = totalQuestions ? Math.min(100, Math.round((answeredCount / totalQuestions) * 100)) : 0;

  return (
    <div className="panel">
      <h2>采访提纲</h2>
      <p className="coverage">覆盖进度：{coverage}%</p>
      <div className="outline-list">
        {outline.map((section) => (
          <div key={section.stage} className="outline-section">
            <h3>{section.stage}</h3>
            <ol>
              {section.questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </div>
  );
}

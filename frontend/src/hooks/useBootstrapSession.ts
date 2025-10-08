// frontend/src/hooks/useBootstrapSession.ts
import { useEffect, useRef } from 'react';
import { useSessionStore } from '../store/useSessionStore';

export function useBootstrapSession(apiBaseUrl: string) {
  const setSession = useSessionStore((state) => state.setSession);
  const setOutline = useSessionStore((state) => state.setOutline);
  const hasBootstrapped = useRef(false); // ✅ 防止重复执行

  useEffect(() => {
    if (hasBootstrapped.current) {
      console.info('[bootstrap] skip (already bootstrapped)');
      return;
    }
    hasBootstrapped.current = true;

    (async () => {
      try {
        console.info('[bootstrap] creating new session...');
        const response = await fetch(`${apiBaseUrl}/v1/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topic: '科技企业采访', interviewer: 'AI采访官' }),
        });
        const data = await response.json();

        const sid = String(data.session.id);
        console.info('[bootstrap] ✅ session created', sid);

        setSession({ sessionId: sid, topic: data.session.topic });
        setOutline(
          data.outline.sections.map((section: any) => ({
            stage: section.stage,
            questions: section.questions.map((q: any) => q.question),
          })),
        );
      } catch (error) {
        console.error('[bootstrap] ❌ failed to create session', error);
      }
    })();
  }, [apiBaseUrl, setOutline, setSession]);
}

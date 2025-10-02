import { useEffect } from 'react';
import { useSessionStore } from '../store/useSessionStore';

export function useBootstrapSession(apiBaseUrl: string) {
  const setSession = useSessionStore((state) => state.setSession);
  const setOutline = useSessionStore((state) => state.setOutline);

  useEffect(() => {
    async function bootstrap() {
      try {
        const response = await fetch(`${apiBaseUrl}/v1/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topic: '科技企业采访', interviewer: 'AI采访官' })
        });
        const data = await response.json();
        setSession({ sessionId: String(data.session.id), topic: data.session.topic });
        setOutline(
          data.outline.sections.map((section: any) => ({
            stage: section.stage,
            questions: section.questions.map((q: any) => q.question)
          }))
        );
      } catch (error) {
        console.error('Failed to bootstrap session', error);
      }
    }
    bootstrap();
  }, [apiBaseUrl, setOutline, setSession]);
}

import '../App.css';
import { OutlinePanel } from '../components/OutlinePanel';
import { PendingClarify } from '../components/PendingClarify';
import { TranscriptPane } from '../components/TranscriptPane';
import { ControlBar } from '../components/ControlBar';
import { useBootstrapSession } from '../hooks/useBootstrapSession';
import { useSessionStore } from '../store/useSessionStore';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export function MainConsole() {
  const stage = useSessionStore((state) => state.stage);
  const pendingQuestion = useSessionStore((state) => state.pendingQuestion);
  const ttsReady = useSessionStore((state) => state.ttsReady);
  useBootstrapSession(API_BASE_URL);

  return (
    <div className="layout">
      <header>
        <h1>采访机器人控制台</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <span className="stage">当前阶段：{stage}</span>
          <span className={`tts-status ${ttsReady ? 'ready' : 'waiting'}`}>
            语音播报：{ttsReady ? '就绪' : '等待连接'}
          </span>
        </div>
      </header>
      <main>
        <section className="left-column">
          <OutlinePanel />
          <PendingClarify />
        </section>
        <section className="right-column">
          <TranscriptPane />
          <div className="next-question">
            <h2>下一轮提问</h2>
            <p>{pendingQuestion || '等待受访者回应...'}</p>
          </div>
        </section>
      </main>
      <ControlBar apiBaseUrl={API_BASE_URL} />
    </div>
  );
}

export default MainConsole;

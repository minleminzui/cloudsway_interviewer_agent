// frontend/src/pages/MainConsole.tsx
import '../App.css';
import { OutlinePanel } from '../components/OutlinePanel';
import { PendingClarify } from '../components/PendingClarify';
import TranscriptPane from '../components/TranscriptPane';
import { ControlBar } from '../components/ControlBar';
import { useBootstrapSession } from '../hooks/useBootstrapSession';
import { useSessionStore } from '../store/useSessionStore';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export function MainConsole() {
  const stage = useSessionStore((state) => state.stage);
  const pendingQuestion = useSessionStore((state) => state.pendingQuestion);
  const ttsReady = useSessionStore((state) => state.ttsReady);
  const ttsMode = useSessionStore((state) => state.ttsMode);
  const ttsError = useSessionStore((state) => state.ttsError);
  const fallbackNeedsClick = useSessionStore((state) => state.ttsFallbackNeedUserAction);
  const fallbackRetry = useSessionStore((state) => state.ttsFallbackRetry);
  const fallbackText = useSessionStore((state) => state.ttsFallbackText);
  useBootstrapSession(API_BASE_URL);

  let ttsStatusClass = 'tts-status';
  let ttsStatusLabel = '等待连接';

  if (ttsMode === 'error') {
    ttsStatusClass += ' error';
    ttsStatusLabel = '故障';
  } else if (ttsMode === 'fallback') {
    ttsStatusClass += ' fallback';
    ttsStatusLabel = '浏览器语音';
  } else if (ttsReady) {
    ttsStatusClass += ' ready';
    ttsStatusLabel = '就绪';
  } else {
    ttsStatusClass += ' waiting';
  }

  const ttsStatusTitle = ttsError ?? undefined;
  const ttsStatusDetail = ttsError && (ttsMode === 'error' || ttsMode === 'fallback') ? `（${ttsError}）` : '';
  const showTtsBanner = Boolean(ttsError && (ttsMode === 'error' || ttsMode === 'fallback'));
  const ttsBannerClass = `tts-banner ${ttsMode}`;
  const allowFallbackRetry =
    ttsMode === 'fallback' && fallbackNeedsClick && Boolean(fallbackRetry) && Boolean(fallbackText);

  return (
    <div className="layout">
      <header>
        <h1>采访机器人控制台</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <span className="stage">当前阶段：{stage}</span>
          <span className={ttsStatusClass} title={ttsStatusTitle}>
            语音播报：{ttsStatusLabel}
            {ttsStatusDetail}
          </span>
        </div>
      </header>
      {showTtsBanner && (
        <div className={ttsBannerClass}>
          {ttsError}
          {allowFallbackRetry && (
            <button type="button" className="tts-retry-button" onClick={() => fallbackRetry?.()}>
              点击重新播报
            </button>
          )}
        </div>
      )}
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

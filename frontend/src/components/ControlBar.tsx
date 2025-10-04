import { FormEvent, useMemo, useState } from 'react';
import { useInterviewClients } from '../hooks/useInterviewClients';

interface ControlBarProps {
  apiBaseUrl: string;
}

export function ControlBar({ apiBaseUrl }: ControlBarProps) {
  const [input, setInput] = useState('');
  const { sendUserUtterance, startMicrophone, stopMicrophone, micStatus, micError } = useInterviewClients(apiBaseUrl);
  const micLabel = useMemo(() => {
    switch (micStatus) {
      case 'starting':
        return '麦克风：请求权限中…';
      case 'recording':
        return '麦克风：录音中';
      case 'error':
        return '麦克风：异常';
      default:
        return '麦克风：未启动';
    }
  }, [micStatus]);
  const micDisabled = micStatus === 'starting';
  const showMicError = micStatus === 'error' && micError;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!input.trim()) return;
    sendUserUtterance(input.trim());
    setInput('');
  };

  const handleMicToggle = () => {
    if (micStatus === 'recording') {
      stopMicrophone();
      return;
    }
    startMicrophone();
  };

  return (
    <form className="control-bar" onSubmit={handleSubmit}>
      <div className="mic-control">
        <button
          type="button"
          className={`mic-button ${micStatus}`}
          onClick={handleMicToggle}
          disabled={micDisabled}
        >
          {micStatus === 'recording' ? '停止录音' : '开始录音'}
        </button>
        <div className={`mic-status-label ${micStatus}`}>{micLabel}</div>
        {showMicError && <div className="mic-error-hint">{micError}</div>}
      </div>
      <input
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder="输入或粘贴转写文本，按 Enter 发送"
      />
      <button type="submit">发送</button>
    </form>
  );
}

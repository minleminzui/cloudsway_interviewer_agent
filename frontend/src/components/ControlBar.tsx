import { FormEvent, useState } from 'react';
import { useInterviewClients } from '../hooks/useInterviewClients';

interface ControlBarProps {
  apiBaseUrl: string;
}

export function ControlBar({ apiBaseUrl }: ControlBarProps) {
  const [input, setInput] = useState('');
  const { sendUserUtterance } = useInterviewClients(apiBaseUrl);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!input.trim()) return;
    sendUserUtterance(input.trim());
    setInput('');
  };

  return (
    <form className="control-bar" onSubmit={handleSubmit}>
      <input
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder="输入或粘贴转写文本，按 Enter 发送"
      />
      <button type="submit">发送</button>
    </form>
  );
}

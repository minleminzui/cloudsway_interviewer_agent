// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { setupGlobalAudioUnlock } from "./utils/setupAudioUnlock";  // ✅ 新增

// 🔹 在 React 启动前初始化 AudioContext 解锁逻辑
setupGlobalAudioUnlock();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

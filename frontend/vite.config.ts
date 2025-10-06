import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      // 🔹 转发所有 WebSocket 到后端 FastAPI
      '/ws': {
        target: 'http://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
      // 🔹 同时让 HTTP API 也可正常走代理（POST /v1/...）
      '/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});

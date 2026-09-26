import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Конфиг исполняется в Node, но типы Node в проект не подключены — описываем только то, что используем.
declare const process: { env: Record<string, string | undefined> };

// Адрес бэкенда для сервера разработки (uvicorn). Host не подменяется: бэкенд сверяет Origin с Host.
const apiTarget = process.env.SAFEROUTE_API ?? "http://127.0.0.1:8098";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
  build: {
    chunkSizeWarningLimit: 800,
  },
});

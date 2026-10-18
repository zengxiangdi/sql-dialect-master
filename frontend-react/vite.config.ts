import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { APP_VERSION } from "./vite.version.js";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const port = Number(env.VITE_PORT || 5174);
  const previewPort = Number(env.VITE_PREVIEW_PORT || 4174);
  return {
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  server: {
    port,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
    },
  },
  preview: {
    port: previewPort,
    strictPort: true,
  },
  build: {
    target: "es2020",
    sourcemap: true,
  },
  };
});

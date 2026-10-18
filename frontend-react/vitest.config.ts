import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { APP_VERSION } from "./vite.version.js";

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});

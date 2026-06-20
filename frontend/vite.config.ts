import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

// Dev server proxies /api and /ws to the backend so the app works same-origin.
// In prod, point VITE_API_BASE at the deployed backend (native shells set this too).
const backendTarget = process.env.DUET_BACKEND_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/ws": {
        target: backendTarget,
        ws: true,
        changeOrigin: true,
      },
      "/media": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
});

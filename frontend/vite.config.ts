import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api and /ws to the backend so the app works same-origin.
// In prod, point VITE_API_BASE at the deployed backend (native shells set this too).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: ["symbols-evaluated-sixth-radio.trycloudflare.com"],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "http://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
      "/media": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

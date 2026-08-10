import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying keeps the SSE stream same-origin, so EventSource needs no CORS
    // dance and the UI works unchanged when the API moves behind a gateway.
    proxy: {
      "/api": {
        // Override with API_TARGET to point the dev server at a second backend
        // (a scratch instance on another port) without editing this file.
        target: process.env.API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});

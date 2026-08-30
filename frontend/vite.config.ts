import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the backend via VITE_API_BASE_URL (default :8000).
// In dev we also proxy /api and /health so a bare fetch works with no env.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});

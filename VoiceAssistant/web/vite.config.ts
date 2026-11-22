import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // Keep the dev proxy in sync with the PORT value used by app.py / voice.ps1.
  const env = loadEnv(mode, ".", "");
  const port = env.PORT || "45123";
  const backend = `http://127.0.0.1:${port}`;

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/ws": {
          target: backend,
          ws: true,
          changeOrigin: true,
        },
        "/api": {
          target: backend,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
    },
  };
});

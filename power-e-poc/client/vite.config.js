import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiPort =
    process.env.POE_API_PORT ||
    env.POE_API_PORT ||
    env.VITE_POE_API_PORT ||
    "3041";
  const apiTarget = `http://127.0.0.1:${apiPort}`;

  return {
    plugins: [react()],
    server: {
      // Evita choque con otro Vite/app habitual en 5173
      port: 5174,
      strictPort: false,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
        "/health": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  };
});

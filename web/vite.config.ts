import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, ".."), "");
  const backendUrl =
    process.env.MEMKIT_BACKEND_URL ??
    env.MEMKIT_BACKEND_URL ??
    "http://127.0.0.1:8077";
  return {
    base: "/ui/",
    envDir: "..",
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      proxy: {
        "/v1": {
          target: backendUrl,
          changeOrigin: false,
          headers: env.MEMKIT_API_KEY ? { "X-API-Key": env.MEMKIT_API_KEY } : undefined,
        },
        "/healthz": { target: backendUrl },
        "/openapi.json": { target: backendUrl },
      },
    },
    build: {
      outDir: "../src/memkit/web_dist",
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes("recharts") || id.includes("d3-")) return "charts";
            if (id.includes("@radix-ui") || id.includes("/cmdk/") || id.includes("react-day-picker")) return "shadcn";
            if (id.includes("@tanstack")) return "tanstack";
            if (id.includes("react-dom") || id.includes("/react/")) return "react";
          },
        },
      },
    },
  };
});

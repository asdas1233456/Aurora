import path from "node:path";
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";


const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }

          if (
            id.includes("/@tanstack/") ||
            id.includes("/zustand/")
          ) {
            return "data-stack";
          }

          if (
            id.includes("/framer-motion/") ||
            id.includes("/lucide-react/")
          ) {
            return "motion-icons";
          }

          if (
            id.includes("/@radix-ui/") ||
            id.includes("/class-variance-authority/") ||
            id.includes("/clsx/") ||
            id.includes("/tailwind-merge/")
          ) {
            return "ui-core";
          }

          if (id.includes("/@xyflow/")) {
            return "graph-flow";
          }

          if (
            id.includes("/react-hook-form/") ||
            id.includes("/@hookform/") ||
            id.includes("/zod/") ||
            id.includes("/react-dropzone/")
          ) {
            return "forms-upload";
          }

          if (id.includes("/react-virtuoso/")) {
            return "logs-virtual";
          }

          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "src/**/*.spec.ts", "src/**/*.spec.tsx"],
    exclude: ["tests/**", "node_modules/**"],
    css: true,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ready": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
  },
});

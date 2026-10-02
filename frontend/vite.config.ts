/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The FastAPI server runs on :8000, started with uvicorn or docker compose.
const API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // During `npm run dev`, API calls are forwarded to FastAPI, so the browser talks to one address.
    proxy: {
      "/api": API,
      "/healthz": API,
      "/docs": API,
      "/openapi.json": API,
    },
  },
  build: {
    // FastAPI serves whatever lands here (see STATIC_DIR in backend/app/main.py).
    outDir: "../backend/app/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    // The app tests click through the whole UI; on a busy machine one can exceed the 5 s default.
    testTimeout: 20_000,
  },
});

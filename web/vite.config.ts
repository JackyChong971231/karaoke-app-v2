/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const server = process.env.KARAOKE_SERVER ?? "http://localhost:8080";
const STRETCH_URL = "/vendor/signalsmith-stretch.mjs";
const stretchSource = resolve(import.meta.dirname, "node_modules/signalsmith-stretch/SignalsmithStretch.mjs");

// The stretch library builds its AudioWorklet from its own functions' source text at runtime. Bundling renames
// identifiers that text depends on, and the worklet then never reports ready. So it ships byte for byte.
function stretchVerbatim(): Plugin {
  return {
    name: "signalsmith-stretch-verbatim",
    configureServer(dev) {
      dev.middlewares.use(STRETCH_URL, (_req, res) => {
        res.setHeader("content-type", "text/javascript");
        res.end(readFileSync(stretchSource));
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: STRETCH_URL.slice(1), source: readFileSync(stretchSource, "utf8") });
    },
  };
}

export default defineConfig({
  plugins: [react(), stretchVerbatim()],
  test: { include: ["src/**/*.test.ts"] },
  define: { __STRETCH_URL__: JSON.stringify(STRETCH_URL) },
  build: {
    rollupOptions: {
      external: [STRETCH_URL],
      input: {
        phone: resolve(import.meta.dirname, "index.html"),
        control: resolve(import.meta.dirname, "control.html"),
        tv: resolve(import.meta.dirname, "tv.html"),
        import: resolve(import.meta.dirname, "import.html"),
      },
    },
  },
  server: {
    proxy: {
      "/ws": { target: server.replace(/^http/, "ws"), ws: true },
      "/api": server,
      "/media": server,
      "/thumb": server,
      "/test": server,
    },
  },
});

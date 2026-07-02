import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

// "miniapp" — внутренний docker-hostname: сервис apps/tiles открывает /tilerender.html
// через сеть compose (vite preview проверяет Host-заголовок).
const allowedHosts = ["okrestmap.ru", "www.okrestmap.ru", "app.okrestmap.ru", "tgbot-afisha.ru", "www.tgbot-afisha.ru", "miniapp"];

export default defineConfig({
  server: {
    host: true,
    port: 5173,
    allowedHosts,
  },
  preview: {
    host: true,
    port: 5173,
    allowedHosts,
  },
  build: {
    // Split the heavy map vendors into their own long-cached chunks.
    rollupOptions: {
      // Второй entry — служебная страница серверного рендера тайлов (apps/tiles).
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        tilerender: fileURLToPath(new URL("./tilerender.html", import.meta.url)),
      },
      output: {
        manualChunks: {
          maplibre: ["maplibre-gl", "@maplibre/maplibre-gl-leaflet"],
          leaflet: ["leaflet", "react-leaflet", "react-leaflet-cluster", "leaflet.markercluster"],
        },
      },
    },
    chunkSizeWarningLimit: 1200,
  },
});

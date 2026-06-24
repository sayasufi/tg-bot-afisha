import { defineConfig } from "vite";

const allowedHosts = ["okrestmap.ru", "www.okrestmap.ru", "app.okrestmap.ru", "tgbot-afisha.ru", "www.tgbot-afisha.ru"];

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

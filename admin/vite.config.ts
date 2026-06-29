import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// admin.okrestmap.ru обслуживается через nginx → этот Vite-preview. Без хоста в allowedHosts Vite
// вернёт 403 (DNS-rebinding guard) — именно та ошибка, что ловили на дефолт-сервере miniapp.
const allowedHosts = ["admin.okrestmap.ru", "localhost", "127.0.0.1"];

export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5174, allowedHosts },
  preview: { host: true, port: 5174, allowedHosts },
});

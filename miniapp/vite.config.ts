import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: true,
    port: 5173,
    allowedHosts: ["tgbot-afisha.ru", "www.tgbot-afisha.ru"],
  },
});

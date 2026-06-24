import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import "leaflet/dist/leaflet.css";
import "../styles.css";

// The actual mount, split into its own (dynamically-imported) chunk so the heavy map bundle
// (maplibre/leaflet/App) is fetched ONLY inside Telegram — a plain browser is redirected by main.tsx
// before this ever loads. The 7s splash fallback lives here too (App removes the splash on map-ready).
export function mountApp(): void {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>
  );

  window.setTimeout(() => {
    const splash = document.getElementById("splash");
    if (splash) {
      splash.classList.add("hide");
      setTimeout(() => splash.remove(), 400);
    }
  }, 7000);
}

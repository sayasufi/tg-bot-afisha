import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import "leaflet/dist/leaflet.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Fade out the instant brand splash once the app has mounted.
const splash = document.getElementById("splash");
if (splash) {
  requestAnimationFrame(() => {
    setTimeout(() => splash.classList.add("hide"), 250);
    setTimeout(() => splash.remove(), 700);
  });
}

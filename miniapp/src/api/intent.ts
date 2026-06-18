import { getWebApp } from "../lib/telegram";
import { API_BASE } from "./http";

// North-star telemetry: a user taking a real INTENT action — opening a route, clicking
// through to tickets/source, sharing, or setting a reminder. Fire-and-forget with
// keepalive so it survives the tab navigating away to the source site / Yandex Maps.
// Never throws and never blocks the action it measures.
export type IntentKind = "click" | "route" | "share" | "reminder" | "calendar";

export function logIntent(kind: IntentKind, eventId?: string): void {
  try {
    const init_data = getWebApp()?.initData || "";
    void fetch(`${API_BASE}/v1/intent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, event_id: eventId, init_data }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* telemetry is best-effort */
  }
}

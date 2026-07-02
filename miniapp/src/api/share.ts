import { API_BASE } from "./http";
import { getAuthPayload } from "../lib/webAuth";

// Ask the backend to prepare a photo inline-message for the current user, so the
// Mini App can share an actual image (not a link) via Telegram.WebApp.shareMessage.
export async function prepareShare(eventId: string): Promise<{ ok: boolean; id?: string }> {
  const initData = getAuthPayload();
  if (!initData) return { ok: false };
  try {
    const res = await fetch(`${API_BASE}/v1/share/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData, event_id: eventId }),
    });
    if (!res.ok) return { ok: false };
    return await res.json();
  } catch {
    return { ok: false };
  }
}

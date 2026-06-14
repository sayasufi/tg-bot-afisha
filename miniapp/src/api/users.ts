import { API_BASE } from "./http";

// Persist the user's home city from their first map geolocation (replaces the
// old in-bot city picker). Best-effort: never blocks the UI, ignores failures,
// and does nothing outside Telegram (no signed initData to authenticate with).
export async function saveUserLocation(lat: number, lon: number): Promise<void> {
  const initData = (window as any)?.Telegram?.WebApp?.initData as string | undefined;
  if (!initData) return;
  try {
    await fetch(`${API_BASE}/v1/users/location`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData, lat, lon }),
      keepalive: true,
    });
  } catch {
    /* saving the city is non-critical */
  }
}

import { API_BASE } from "./http";

function initData(): string | undefined {
  return (window as any)?.Telegram?.WebApp?.initData as string | undefined;
}

export type EventSuggestInput = {
  title: string;
  date_start: string; // ISO / datetime-local; server assumes Moscow time if no offset
  date_end?: string | null;
  venue?: string;
  address?: string;
  category?: string;
  price_min?: number | null;
  price_max?: number | null;
  is_free?: boolean;
  url?: string;
  image?: string;
  description?: string;
  city?: string;
};

export type SuggestResult = { ok: true; submissionId: string } | { ok: false; error: string };

function readDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || ""));
    r.onerror = () => reject(new Error("read"));
    r.readAsDataURL(file);
  });
}

// Upload a poster/photo (as a base64 data URL) → returns the stored public URL to put in the form.
// We send the ORIGINAL file (not a canvas re-encode): a canvas toDataURL drops the EXIF orientation tag,
// so portrait phone photos arrived sideways on webviews that don't auto-orient. The server validates,
// EXIF-rotates and downscales to 1600px; the client only enforces the 8MB size cap, whose base64 (~10.7MB)
// stays under the 12MB proxy limit.
export async function uploadSuggestImage(
  file: File,
): Promise<{ ok: true; url: string } | { ok: false; error: string }> {
  const init = initData();
  if (!init) return { ok: false, error: "Открой приложение из Telegram" };
  let dataUrl: string;
  try {
    dataUrl = await readDataUrl(file);
  } catch {
    return { ok: false, error: "Не удалось прочитать файл" };
  }
  try {
    const r = await fetch(`${API_BASE}/v1/suggest/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, data_url: dataUrl }),
    });
    if (r.ok) {
      const j = await r.json();
      return { ok: true, url: String(j.url ?? "") };
    }
    let detail = "Не удалось загрузить фото";
    try {
      const j = await r.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* non-JSON error body */
    }
    return { ok: false, error: detail };
  } catch {
    return { ok: false, error: "Нет связи. Попробуй ещё раз." };
  }
}

// Submit a Telegram channel (of a venue / the user's own) as a source for moderation.
export async function suggestChannel(username: string, city?: string): Promise<SuggestResult> {
  const init = initData();
  if (!init) return { ok: false, error: "Открой приложение из Telegram" };
  try {
    const r = await fetch(`${API_BASE}/v1/suggest/channel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, username, city }),
    });
    if (r.ok) {
      const j = await r.json();
      return { ok: true, submissionId: String(j.submission_id ?? "") };
    }
    let detail = "Не удалось отправить";
    try {
      const j = await r.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* non-JSON error body */
    }
    return { ok: false, error: detail };
  } catch {
    return { ok: false, error: "Нет связи. Попробуй ещё раз." };
  }
}

// Submit a user event for admin moderation. Authenticated via signed Telegram initData; returns a
// friendly error string (never throws) so the form can show it inline.
export async function suggestEvent(input: EventSuggestInput): Promise<SuggestResult> {
  const init = initData();
  if (!init) return { ok: false, error: "Открой приложение из Telegram" };
  try {
    const r = await fetch(`${API_BASE}/v1/suggest/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, ...input }),
    });
    if (r.ok) {
      const j = await r.json();
      return { ok: true, submissionId: String(j.submission_id ?? "") };
    }
    let detail = "Не удалось отправить";
    try {
      const j = await r.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* non-JSON error body */
    }
    return { ok: false, error: detail };
  } catch {
    return { ok: false, error: "Нет связи. Попробуй ещё раз." };
  }
}

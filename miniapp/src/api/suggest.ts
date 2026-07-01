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
  description?: string;
  city?: string;
};

export type SuggestResult = { ok: true; submissionId: string } | { ok: false; error: string };

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

import { useState } from "react";
import { createPortal } from "react-dom";

import { suggestChannel } from "../../api/suggest";
import type { City } from "../../api/types";
import { IconClose } from "../../lib/icons";
import { hapticNotify } from "../../lib/telegram";

// Full-screen form to add a Telegram channel as an event source; posts to /v1/suggest/channel →
// admin moderation. Portaled to <body> so it overlays the profile panel. The city is chosen here
// (default = the user's city, but the channel may cover a DIFFERENT city — the submitter knows it).
export function SuggestChannelModal({
  open,
  onClose,
  cities,
  defaultCity,
}: {
  open: boolean;
  onClose: () => void;
  cities: City[];
  defaultCity: string;
}) {
  const [username, setUsername] = useState("");
  const [city, setCity] = useState(defaultCity || cities[0]?.slug || "");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  const canSubmit = username.trim().replace(/^@/, "").length >= 5 && !!city;

  async function submit() {
    if (!canSubmit || busy) return;
    setBusy(true);
    setErr(null);
    const res = await suggestChannel(username.trim(), city);
    setBusy(false);
    if (res.ok) {
      hapticNotify("success");
      setDone(true);
    } else {
      setErr(res.error);
      hapticNotify("error");
    }
  }

  return createPortal(
    <div className="suggest" role="dialog" aria-modal="true" aria-label="Добавить свой канал">
      <header className="panelview__head">
        <h2>добавить канал</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll">
        {done ? (
          <div className="suggest__done">
            <div className="suggest__done-glyph" aria-hidden="true">✓</div>
            <div className="suggest__done-title">Спасибо!</div>
            <div className="suggest__done-sub">
              Отправили на проверку. Если канал подходит — подключим, и бот напишет. События появятся в течение суток.
            </div>
            <button type="button" className="suggest__submit" onClick={onClose}>Готово</button>
          </div>
        ) : (
          <>
            <p className="suggest__lead">
              Ведёшь Telegram-канал площадки или событий своего города? Добавь его — будем собирать афишу
              оттуда автоматически.
            </p>
            <label className="suggest__field">
              <span className="suggest__label">@username канала *</span>
              <input
                className="suggest__input"
                value={username}
                maxLength={120}
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                placeholder="@myvenue"
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="suggest__field">
              <span className="suggest__label">Город канала *</span>
              <select className="suggest__input" value={city} onChange={(e) => setCity(e.target.value)}>
                {cities.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
              </select>
            </label>
            <div className="suggest__hint">
              Только публичный канал (не приватный). Город нужен, чтобы события встали на карту в нужном месте.
            </div>
            {err && <div className="suggest__err">{err}</div>}
            <button type="button" className="suggest__submit" disabled={!canSubmit || busy} onClick={submit}>
              {busy ? "Отправляем…" : "Отправить на модерацию"}
            </button>
            <div className="suggest__fine">Заявки проверяет модератор. Только афиша-каналы — рекламные/личные не пройдут.</div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

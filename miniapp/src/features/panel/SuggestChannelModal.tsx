import { useState } from "react";
import { createPortal } from "react-dom";

import { suggestChannel } from "../../api/suggest";
import { IconClose } from "../../lib/icons";
import { hapticNotify } from "../../lib/telegram";

// Full-screen form to add a Telegram channel as an event source; posts to /v1/suggest/channel →
// admin moderation. Portaled to <body> so it overlays the profile panel.
export function SuggestChannelModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  const canSubmit = username.trim().replace(/^@/, "").length >= 5;

  async function submit() {
    if (!canSubmit || busy) return;
    setBusy(true);
    setErr(null);
    const res = await suggestChannel(username.trim());
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
            <div className="suggest__hint">Только публичный канал (не приватный). Город определим по твоему профилю.</div>
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

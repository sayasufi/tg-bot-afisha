import { useEffect, useState } from "react";

import {
  authLinkCode,
  authLogin,
  authMe,
  authRegister,
  getWebToken,
  logoutWeb,
} from "../../lib/webAuth";
import { showToast } from "../../lib/toast";

// Аккаунт веб-версии (браузер без Telegram): вход/регистрация по email+паролю и связка с
// Telegram-аккаунтом. Рендерится ВМЕСТО ProfilePanel в веб-режиме. Стили — те же, что у
// онбординга (общий full-screen sheet бренда), инпуты — локальные.
const input: React.CSSProperties = {
  width: "100%",
  height: 44,
  padding: "0 12px",
  background: "var(--plinth)",
  color: "var(--ink)",
  border: 0,
  boxShadow: "inset 0 0 0 1px var(--ink)",
  fontSize: 15,
};

export function WebAccountPanel({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<{ email: string | null; telegram_linked: boolean } | null>(null);
  const authed = !!getWebToken();

  useEffect(() => {
    if (!authed) return;
    void authMe().then((m) => {
      if (m && !m.exists) {
        // Аккаунт слит в Telegram (связка состоялась) — старый веб-uid исчез: чистим сессию,
        // юзер логинится по email заново и попадает в объединённый аккаунт.
        logoutWeb();
        window.location.reload();
        return;
      }
      if (m) setMe({ email: m.email, telegram_linked: m.telegram_linked });
    });
  }, [authed]);

  const submit = async () => {
    setError(null);
    if (!email.trim() || password.length < 8) {
      setError(password.length < 8 ? "Пароль — минимум 8 символов" : "Укажи email");
      return;
    }
    setBusy(true);
    const r = mode === "login" ? await authLogin(email, password) : await authRegister(email, password);
    setBusy(false);
    if (!r.ok) {
      setError(r.data.detail || "Не получилось — попробуй ещё раз");
      return;
    }
    showToast(mode === "login" ? "С возвращением!" : "Аккаунт создан", { tone: "good" });
    window.location.reload(); // чистый ре-бутстрап уже с сессией (избранное/настройки подтянутся)
  };

  const link = async () => {
    const url = await authLinkCode();
    if (!url) {
      showToast("Не получилось — попробуй позже", { tone: "muted" });
      return;
    }
    window.open(url, "_blank"); // t.me/бот?start=link_<код> → бот сливает аккаунты
  };

  return (
    <div className="onboard" role="dialog" aria-modal="true" aria-label="Аккаунт">
      <div className="onboard__sheet">
        <span className="onboard__kicker">ОКРЕСТ · АККАУНТ</span>

        {authed ? (
          <>
            <h2 className="onboard__title">{me?.email ?? "аккаунт"}</h2>
            <p className="onboard__lede">
              {me?.telegram_linked
                ? "Telegram связан — напоминания и еженедельная афиша приходят в бот."
                : "Свяжи Telegram: избранное станет общим, а бот будет присылать напоминания за 2 часа до начала и афишу на выходные."}
            </p>
            <div className="onboard__foot">
              {!me?.telegram_linked && (
                <button type="button" className="onboard__cta onboard__cta--ready" onClick={link}>
                  Связать Telegram →
                </button>
              )}
              <button type="button" className="onboard__skip" onClick={onClose}>
                к карте
              </button>
              <button
                type="button"
                className="onboard__skip"
                onClick={() => {
                  logoutWeb();
                  window.location.reload();
                }}
              >
                выйти
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 className="onboard__title">{mode === "login" ? "вход" : "регистрация"}</h2>
            <p className="onboard__lede">
              Аккаунт хранит избранное и настройки. Позже его можно связать с Telegram — тогда бот
              будет напоминать о сохранённых событиях.
            </p>
            <div style={{ display: "grid", gap: 10, margin: "14px 0 4px" }}>
              <input
                style={input}
                type="email"
                placeholder="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <input
                style={input}
                type="password"
                placeholder={mode === "register" ? "пароль (мин. 8 символов)" : "пароль"}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !busy && void submit()}
              />
              {error && <div style={{ color: "var(--cinnabar)", fontSize: 13 }}>{error}</div>}
            </div>
            <div className="onboard__foot">
              <button
                type="button"
                className="onboard__cta onboard__cta--ready"
                disabled={busy}
                onClick={() => void submit()}
              >
                {busy ? "…" : mode === "login" ? "Войти →" : "Создать аккаунт →"}
              </button>
              <button
                type="button"
                className="onboard__skip"
                onClick={() => {
                  setMode(mode === "login" ? "register" : "login");
                  setError(null);
                }}
              >
                {mode === "login" ? "нет аккаунта — регистрация" : "уже есть аккаунт — войти"}
              </button>
              <button type="button" className="onboard__skip" onClick={onClose}>
                позже — просто смотреть карту
              </button>
              {mode === "login" && (
                <p style={{ fontSize: 12, opacity: 0.65, marginTop: 6 }}>
                  Забыли пароль? Напишите менеджеру @okrest_manager
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

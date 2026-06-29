import { useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export function Login() {
  const { loginWithWidget } = useAuth();
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    (window as any).onTelegramAuth = async (u: any) => {
      setErr(null);
      try {
        await loginWithWidget(u);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          setErr("доступ запрещён — аккаунт не в списке владельцев или подпись недействительна");
        } else if (e instanceof ApiError && e.status === 429) {
          setErr("слишком много попыток, подождите минуту");
        } else {
          setErr("не удалось войти");
        }
      }
    };

    const bot = (import.meta as any).env?.VITE_TG_BOT || "okrestmap_bot";
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.setAttribute("data-telegram-login", bot);
    s.setAttribute("data-size", "large");
    s.setAttribute("data-userpic", "false");
    s.setAttribute("data-onauth", "onTelegramAuth(user)");
    s.setAttribute("data-request-access", "write");
    ref.current?.appendChild(s);

    return () => {
      (window as any).onTelegramAuth = undefined;
    };
  }, []);

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">
          <span className="o">о</span>крест
        </div>
        <div className="login__kicker">панель управления</div>
        <p className="login__hint">
          Вход только для владельца.
          <br />
          Авторизуйтесь через Telegram.
        </p>
        <div className="login__widget" ref={ref} />
        {err && <div className="login__err">{err}</div>}
        <div className="login__note">
          Кнопка не появилась? Домен admin.okrestmap.ru должен быть привязан к боту: BotFather → /setdomain.
        </div>
      </div>
    </div>
  );
}

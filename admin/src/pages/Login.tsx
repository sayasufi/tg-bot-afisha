import { FormEvent, useState } from "react";

import { Logo } from "../components/Logo";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(username, password);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setErr("неверный логин или пароль");
      else if (e instanceof ApiError && e.status === 429) setErr("слишком много попыток, подождите минуту");
      else if (e instanceof ApiError && e.status === 404) setErr("админка не настроена на сервере");
      else setErr("не удалось войти");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login__card">
        <div style={{ marginBottom: 14 }}>
          <Logo size={46} />
        </div>
        <div className="login__brand">
          <span className="o">о</span>крест
        </div>
        <div className="login__kicker">панель управления</div>

        <form className="login__form" onSubmit={submit}>
          <div>
            <label className="login__label">логин</label>
            <input
              className="login__input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
            />
          </div>
          <div>
            <label className="login__label">пароль</label>
            <input
              className="login__input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {err && <div className="login__err">{err}</div>}
          <button className="btn login__submit" type="submit" disabled={busy}>
            {busy ? "вход…" : "войти"}
          </button>
        </form>
      </div>
    </div>
  );
}

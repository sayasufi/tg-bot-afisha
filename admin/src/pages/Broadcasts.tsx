import { useState } from "react";

import { StatCard, fmtNum } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

export function Broadcasts() {
  const { data, error, loading, reload } = useApi<any>("/broadcast/recipients", 60000);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const test = async (kind: "digest" | "reminder") => {
    setBusy(kind);
    setMsg(null);
    try {
      const r = await apiPost("/broadcast/test", { kind });
      const what = kind === "digest" ? "дайджест" : "напоминание";
      setMsg(r.sent ? `✓ ${what} отправлено на тест-аккаунт (${r.to}) — проверь Telegram` : `отправлено 0 — нет контента для превью`);
    } catch (e: any) {
      const d = e?.message ?? "не удалось";
      setMsg(`ошибка: ${d}`);
    } finally {
      setBusy(null);
      reload();
    }
  };

  const testReady = !!data?.test_user_id;

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">рассылки</h1>
          <div className="page__sub">тест себе + кто сколько получает</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="section__title">получатели</div>
          <div className="statgrid">
            <StatCard num={fmtNum(data.total)} label="всего пользователей" accent />
            <StatCard num={fmtNum(data.digest_optin)} label="подписаны на дайджест" sub="боевой дайджест уйдёт стольким" />
            <StatCard num={fmtNum(data.reminder_optin)} label="напоминания не отключали" />
            <StatCard num={fmtNum(data.active_7d)} label="активны за 7д" />
          </div>

          <div className="section__title">тест себе</div>
          <div className="bcast-note">
            Тест уходит <b>только</b> на тест-аккаунт{" "}
            {testReady ? <span className="code">{data.test_user_id}</span> : "(не задан — кнопки выключены)"} — реальных
            пользователей это <b>не</b> касается. Боевые рассылки тут не запускаются: недельный дайджест и напоминания
            идут по расписанию (раздел «Процессы»), там же можно прогнать вручную.
          </div>
          <div className="bcast-actions">
            <button className="btn" disabled={!testReady || !!busy} onClick={() => test("digest")}>
              {busy === "digest" ? "отправляю…" : "тест дайджеста себе"}
            </button>
            <button className="btn btn--ghost" disabled={!testReady || !!busy} onClick={() => test("reminder")}>
              {busy === "reminder" ? "отправляю…" : "тест напоминания себе"}
            </button>
          </div>
          {msg && <div className="bcast-msg">{msg}</div>}
        </>
      )}
    </div>
  );
}

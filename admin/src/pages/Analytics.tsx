import { useState } from "react";

import { BarChart } from "../components/BarChart";
import { useApi } from "../lib/useApi";

const ACTION_LABELS: Record<string, string> = {
  click: "открытия",
  route: "маршруты",
  share: "шеры",
  reminder: "напоминания",
  calendar: "в календарь",
};

export function Analytics() {
  const { data, error, loading, reload } = useApi<any>("/stats/timeseries", 60000);
  const [kind, setKind] = useState("click");

  const kinds = data?.actions ? Object.keys(data.actions) : [];

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">аналитика</h1>
          <div className="page__sub">тренды вовлечённости и роста каталога</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="section__title">WAU · недельная аудитория (8 недель, № ISO-недели)</div>
          <BarChart data={data.wau} />

          <div className="section__title topbar" style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <span>действия за 14 дней</span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              style={{ height: 28, background: "var(--vitrine)", border: "1px solid var(--line)", color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 11, padding: "0 8px" }}
            >
              {kinds.map((k) => (
                <option key={k} value={k}>{ACTION_LABELS[k] ?? k}</option>
              ))}
            </select>
          </div>
          <BarChart data={data.actions?.[kind] ?? []} />

          <div className="section__title">новые события по дням (объём ингеста, 14 дней)</div>
          <BarChart data={data.new_events} />

          <div className="section__title">новые пользователи по дням (14 дней)</div>
          <BarChart data={data.new_users} />
        </>
      )}
    </div>
  );
}

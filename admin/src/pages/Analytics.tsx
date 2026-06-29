import { useMemo, useState } from "react";

import { LineChart } from "../components/LineChart";
import { StatCard, fmtNum } from "../components/ui";
import { useApi } from "../lib/useApi";

const ACTIONS: Record<string, { label: string; hint: string }> = {
  click: { label: "Открыли событие", hint: "открытий карточки события" },
  route: { label: "Построили маршрут", hint: "построений маршрута до площадки" },
  share: { label: "Поделились «пойдём?»", hint: "отправок события другу" },
};

const RANGES = [
  { v: "today", label: "сегодня" },
  { v: "yesterday", label: "вчера" },
  { v: "7d", label: "7 дней" },
  { v: "14d", label: "14 дней" },
  { v: "30d", label: "30 дней" },
  { v: "90d", label: "90 дней" },
  { v: "custom", label: "период…" },
];
const BUCKET_LABEL: Record<string, string> = { hour: "по часам", day: "по дням", month: "по месяцам" };

function Chart({ title, hint, data }: { title: string; hint: string; data: { label: string; value: number }[] }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div className="section__title" style={{ marginBottom: 2 }}>{title}</div>
      <div className="chart-hint">{hint}</div>
      <LineChart data={data} />
    </div>
  );
}

export function Analytics() {
  const [range, setRange] = useState("14d");
  const [frm, setFrm] = useState("");
  const [to, setTo] = useState("");

  const path = useMemo(() => {
    const p = new URLSearchParams({ range });
    if (range === "custom" && frm && to) {
      p.set("frm", new Date(frm).toISOString());
      p.set("to", new Date(to + "T23:59:59").toISOString());
    }
    return `/stats/timeseries?${p.toString()}`;
  }, [range, frm, to]);

  const { data, error, loading, reload } = useApi<any>(path, 60000);
  const actionKinds: string[] = data?.actions ? Object.keys(data.actions) : [];
  const kpi = data?.kpi;
  const win = data?.bucket ? BUCKET_LABEL[data.bucket] : "";

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">аналитика</h1>
          <div className="page__sub">как пользуются приложением и как растёт каталог · время МСК</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        {RANGES.map((r) => (
          <button key={r.v} className={"chip" + (range === r.v ? " chip--on" : "")} onClick={() => setRange(r.v)}>{r.label}</button>
        ))}
        {range === "custom" && (
          <>
            <input type="date" value={frm} onChange={(e) => setFrm(e.target.value)} />
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </>
        )}
        {win && <span className="filter-count">график {win}</span>}
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          {kpi && (
            <div className="statgrid">
              <StatCard num={fmtNum(kpi.opens)} label="открыли событие" accent />
              <StatCard num={fmtNum(kpi.routes)} label="построили маршрут" />
              <StatCard num={fmtNum(kpi.shares)} label="поделились «пойдём?»" />
              <StatCard num={fmtNum(kpi.active_users)} label="активных пользователей" />
              <StatCard num={fmtNum(kpi.new_users)} label="новых пользователей" />
              <StatCard num={fmtNum(kpi.new_events)} label="новых событий" />
            </div>
          )}

          <Chart title="Активные пользователи по неделям" hint="сколько разных людей заходили и что-то делали (по ISO-неделям интервала)" data={data.wau} />

          {actionKinds.map((k) => (
            <Chart key={k} title={`${ACTIONS[k]?.label ?? k} — ${win}`} hint={`${ACTIONS[k]?.hint ?? ""} за интервал`} data={data.actions[k]} />
          ))}

          <Chart title={`Новые события — ${win}`} hint="сколько новых событий подтянулось из источников" data={data.new_events} />
          <Chart title={`Новые пользователи — ${win}`} hint="сколько новых людей впервые зашли" data={data.new_users} />
        </>
      )}
    </div>
  );
}

import { useMemo, useState } from "react";

import { SortTh, useSort } from "../components/sortable";
import { Badge } from "../components/ui";
import { apiPost } from "../lib/api";
import { useMutate } from "../lib/mutate";
import { useApi } from "../lib/useApi";

type Source = {
  source_id: number;
  name: string;
  kind: string;
  family: string;
  city: string | null;
  city_slug: string | null;
  is_active: boolean;
  crawl_interval_sec: number;
  last_status: string | null;
  last_finished: string | null;
};

const STATUS_KIND: Record<string, "ok" | "warn" | "down" | "off"> = {
  success: "ok",
  running: "warn",
  pending: "warn",
  failed: "down",
  error: "down",
};
const STATUS_LABEL: Record<string, string> = {
  success: "успех",
  running: "идёт",
  pending: "ожидание",
  failed: "ошибка",
  error: "ошибка",
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} дн назад`;
}

function fmtInterval(sec: number): string {
  if (sec >= 86400) return `${Math.round(sec / 86400)} дн`;
  if (sec >= 3600) return `${Math.round(sec / 3600)} ч`;
  if (sec >= 60) return `${Math.round(sec / 60)} мин`;
  return `${sec} с`;
}

const SORT_GET = (s: Source, k: string): any => {
  switch (k) {
    case "family": return s.family;
    case "city": return s.city;
    case "active": return s.is_active ? 0 : 1;
    case "interval": return s.crawl_interval_sec;
    case "last": return s.last_finished;
    default: return s.name;
  }
};

export function Sources() {
  const { data, error, loading, reload } = useApi<{ items: Source[]; total: number }>("/sources", 60000);
  const all = data?.items ?? [];

  const [q, setQ] = useState("");
  const [family, setFamily] = useState("");
  const [city, setCity] = useState("");
  const [active, setActive] = useState("");

  const families = useMemo(() => [...new Set(all.map((s) => s.family))].sort(), [all]);
  const cities = useMemo(
    () => [...new Set(all.map((s) => s.city).filter((c): c is string => !!c))].sort((a, b) => a.localeCompare(b, "ru")),
    [all]
  );

  const filtered = useMemo(
    () =>
      all.filter(
        (s) =>
          (!q || s.name.toLowerCase().includes(q.toLowerCase())) &&
          (!family || s.family === family) &&
          (!city || s.city === city) &&
          (!active || String(s.is_active) === active)
      ),
    [all, q, family, city, active]
  );

  const { sorted, sort, onSort } = useSort(filtered, SORT_GET, { key: "name", dir: "asc" });
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const mutate = useMutate();

  const toggle = async (s: Source) => {
    setBusy((b) => ({ ...b, [s.source_id]: true }));
    try {
      await mutate(() => apiPost(`/sources/${s.source_id}/toggle`, { active: !s.is_active }));
      reload();
    } finally {
      setBusy((b) => ({ ...b, [s.source_id]: false }));
    }
  };

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">источники</h1>
          <div className="page__sub">{data ? `${data.total} источников сбора событий` : "источники сбора событий"}</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        <input placeholder="поиск по имени…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={family} onChange={(e) => setFamily(e.target.value)}>
          <option value="">все источники</option>
          {families.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select value={city} onChange={(e) => setCity(e.target.value)}>
          <option value="">все города</option>
          {cities.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select value={active} onChange={(e) => setActive(e.target.value)}>
          <option value="">любой статус</option>
          <option value="true">активные</option>
          <option value="false">выключенные</option>
        </select>
        <span className="filter-count">показано {sorted.length}</span>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <SortTh label="семейство" k="family" sort={sort} onSort={onSort} />
                <SortTh label="источник" k="name" sort={sort} onSort={onSort} />
                <SortTh label="город" k="city" sort={sort} onSort={onSort} />
                <SortTh label="активен" k="active" sort={sort} onSort={onSort} />
                <SortTh label="интервал" k="interval" sort={sort} onSort={onSort} />
                <SortTh label="последний прогон" k="last" sort={sort} onSort={onSort} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.source_id}>
                  <td className="muted">{s.family}</td>
                  <td className="code">{s.name}</td>
                  <td className="muted">{s.city ?? "—"}</td>
                  <td>
                    <button className="iconbtn" disabled={!!busy[s.source_id]} onClick={() => toggle(s)} title={s.is_active ? "выключить" : "включить"}>
                      {s.is_active ? <Badge kind="ok">вкл</Badge> : <Badge kind="off">выкл</Badge>}
                    </button>
                  </td>
                  <td
                    className="muted"
                    title="расписание задаётся в Prefect (раздел Процессы); это поле информативно"
                  >
                    {fmtInterval(s.crawl_interval_sec)}
                  </td>
                  <td>
                    {s.last_status ? (
                      <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                        <Badge kind={STATUS_KIND[s.last_status] ?? "off"}>{STATUS_LABEL[s.last_status] ?? s.last_status}</Badge>
                        <span className="muted">{ago(s.last_finished)}</span>
                      </span>
                    ) : (
                      <span className="muted">— нет прогонов</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

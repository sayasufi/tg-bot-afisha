import { useEffect, useMemo, useState } from "react";

import { SortTh } from "../components/sortable";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

type V = {
  venue_id: number;
  name: string;
  city: string;
  address: string;
  has_coords: boolean;
  has_hours: boolean;
  geocode_provider: string;
  geocode_confidence: number;
  n_events: number;
};

const MISSING_OPTS = [
  { v: "", label: "все площадки" },
  { v: "coords", label: "без координат" },
  { v: "hours", label: "без часов" },
];

export function Venues() {
  const facets = useApi<{ cities: string[] }>("/venues/facets");
  const flows = useApi<any>("/flows");

  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [city, setCity] = useState("");
  const [missing, setMissing] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "events", dir: "desc" });
  const [page, setPage] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => {
      setQd(q);
      setPage(0);
    }, 350);
    return () => clearTimeout(t);
  }, [q]);

  const onSort = (k: string) => {
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "asc" }));
    setPage(0);
  };

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (qd.trim()) p.set("q", qd.trim());
    if (city) p.set("city", city);
    if (missing) p.set("missing", missing);
    p.set("sort", sort.key);
    p.set("dir", sort.dir);
    if (page) p.set("page", String(page));
    return `/venues?${p.toString()}`;
  }, [qd, city, missing, sort, page]);

  const { data, error, loading, reload } = useApi<any>(path);
  const items: V[] = data?.items ?? [];
  const resetTo = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(0);
  };

  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 100;
  const pages = Math.max(1, Math.ceil(total / pageSize));

  // Точечные фиксы = батч-прогоны Prefect по всему каталогу (не одной площадке) — кнопки в хедере.
  const deployBy = (name: string) => (flows.data?.flows ?? []).find((f: any) => f.name === name);
  const [sweep, setSweep] = useState<string | null>(null);
  const runSweep = async (name: string, human: string) => {
    const f = deployBy(name);
    if (!f) return;
    if (!window.confirm(`«${human}» — это полный прогон по всему каталогу площадок (не по одной). Запустить?`)) return;
    setSweep(name);
    try {
      await apiPost("/ops/run", { deployment_id: f.id, name: f.name });
    } finally {
      setTimeout(() => setSweep(null), 1500);
    }
  };

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">площадки</h1>
          <div className="page__sub">{data ? `${total.toLocaleString("ru-RU")} площадок по фильтру` : "каталог площадок"}</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {deployBy("correct-venue-coords") && (
            <button className="btn btn--ghost" disabled={sweep != null} onClick={() => runSweep("correct-venue-coords", "пересчёт координат")} title="батч-прогон: перегеокодировать площадки с неточными пинами">
              {sweep === "correct-venue-coords" ? "запущено…" : "пересчитать координаты"}
            </button>
          )}
          {deployBy("resolve-venue-hours") && (
            <button className="btn btn--ghost" disabled={sweep != null} onClick={() => runSweep("resolve-venue-hours", "обновление часов")} title="батч-прогон: подтянуть часы работы для площадок без них">
              {sweep === "resolve-venue-hours" ? "запущено…" : "обновить часы"}
            </button>
          )}
          <button className="btn btn--ghost" onClick={reload}>обновить</button>
        </div>
      </div>

      <div className="filterbar">
        <input placeholder="поиск по названию/адресу…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={city} onChange={(e) => resetTo(setCity)(e.target.value)}>
          <option value="">все города</option>
          {(facets.data?.cities ?? []).map((cc) => (
            <option key={cc} value={cc}>{cc}</option>
          ))}
        </select>
        <select value={missing} onChange={(e) => resetTo(setMissing)(e.target.value)}>
          {MISSING_OPTS.map((m) => (
            <option key={m.v} value={m.v}>{m.label}</option>
          ))}
        </select>
        <span className="filter-count">{loading ? "…" : `показано ${items.length}`}</span>
      </div>

      {error && <div className="state state--err">ошибка: {error}</div>}
      {loading && !data && <div className="state">загрузка…</div>}

      {data && (
        <>
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr>
                  <SortTh label="название" k="name" sort={sort} onSort={onSort} />
                  <SortTh label="город" k="city" sort={sort} onSort={onSort} />
                  <th>адрес</th>
                  <SortTh label="событий" k="events" sort={sort} onSort={onSort} className="num" />
                  <th>коорд.</th>
                  <th>часы</th>
                  <th>геокод</th>
                </tr>
              </thead>
              <tbody>
                {items.map((v) => (
                  <tr key={v.venue_id}>
                    <td>{v.name || "—"}</td>
                    <td className="muted">{v.city || "—"}</td>
                    <td className="muted" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.address || "—"}</td>
                    <td className="num">{v.n_events}</td>
                    <td className="muted" style={!v.has_coords ? { color: "var(--cinnabar)" } : undefined}>{v.has_coords ? "✓" : "—"}</td>
                    <td className="muted">{v.has_hours ? "✓" : "—"}</td>
                    <td className="muted">{(v.geocode_provider || "—") + (v.geocode_confidence ? ` ${v.geocode_confidence.toFixed(2)}` : "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pager">
            <button className="iconbtn" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← назад</button>
            <span className="filter-count" style={{ margin: 0 }}>стр {page + 1} из {pages}</span>
            <button className="iconbtn" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>вперёд →</button>
          </div>
        </>
      )}
    </div>
  );
}

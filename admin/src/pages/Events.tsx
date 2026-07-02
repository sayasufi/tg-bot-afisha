import { useEffect, useMemo, useState } from "react";

import { SortTh } from "../components/sortable";
import { Badge } from "../components/ui";
import { apiPost } from "../lib/api";
import { useMutate } from "../lib/mutate";
import { useApi } from "../lib/useApi";

type Ev = {
  event_id: string;
  code: string | null;
  title: string;
  category: string;
  status: string;
  has_image: boolean;
  next_date: string | null;
  city: string | null;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "2-digit" });
}

const DATE_OPTS = [
  { v: "", label: "любые даты" },
  { v: "upcoming", label: "предстоящие" },
  { v: "week", label: "на этой неделе" },
  { v: "past", label: "прошедшие" },
];

export function Events() {
  const facets = useApi<{ categories: string[]; statuses: string[]; cities: string[] }>("/events/facets");

  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [city, setCity] = useState("");
  const [date, setDate] = useState("");
  // дефолт — новые добавленные первыми (created desc; «дата» с 2014-го первой была бы бесполезна).
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "created", dir: "desc" });
  const [page, setPage] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => {
      setQd(q);
      setPage(0);
    }, 350);
    return () => clearTimeout(t);
  }, [q]);

  // Серверная сортировка: ключ/направление едут в запрос → ORDER BY по ВСЕМУ набору, не по странице.
  const onSort = (k: string) => {
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "asc" }));
    setPage(0);
  };

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (qd.trim()) p.set("q", qd.trim());
    if (status) p.set("status", status);
    if (category) p.set("category", category);
    if (city) p.set("city", city);
    if (date) p.set("date", date);
    p.set("sort", sort.key);
    p.set("dir", sort.dir);
    if (page) p.set("page", String(page));
    return `/events?${p.toString()}`;
  }, [qd, status, category, city, date, sort, page]);

  const { data, error, loading, reload } = useApi<any>(path);
  const items: Ev[] = data?.items ?? [];
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const setBusyFor = (id: string, v: boolean) => setBusy((b) => ({ ...b, [id]: v }));
  const mutate = useMutate();

  const toggleStatus = async (e: Ev) => {
    setBusyFor(e.event_id, true);
    try {
      await mutate(() => apiPost(`/events/${e.event_id}`, { status: e.status === "active" ? "hidden" : "active" }));
      reload();
    } finally {
      setBusyFor(e.event_id, false);
    }
  };

  // Категория — только из facets.categories (было window.prompt → любой мусор-текст
  // прилетал в БД как валидная категория). Пустой/тот же — no-op.
  const reclassify = async (e: Ev, cat: string) => {
    if (!cat || cat === e.category) return;
    setBusyFor(e.event_id, true);
    try {
      await mutate(() => apiPost(`/events/${e.event_id}`, { category: cat }));
      reload();
    } finally {
      setBusyFor(e.event_id, false);
    }
  };

  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 100;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const resetTo = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(0);
  };

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">события</h1>
          <div className="page__sub">{data ? `${total.toLocaleString("ru-RU")} событий по фильтру` : "каталог событий"}</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        <input placeholder="поиск по названию…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => resetTo(setStatus)(e.target.value)}>
          <option value="">любой статус</option>
          {(facets.data?.statuses ?? []).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={category} onChange={(e) => resetTo(setCategory)(e.target.value)}>
          <option value="">все категории</option>
          {(facets.data?.categories ?? []).map((cc) => (
            <option key={cc} value={cc}>{cc}</option>
          ))}
        </select>
        <select value={city} onChange={(e) => resetTo(setCity)(e.target.value)}>
          <option value="">все города</option>
          {(facets.data?.cities ?? []).map((cc) => (
            <option key={cc} value={cc}>{cc}</option>
          ))}
        </select>
        <select value={date} onChange={(e) => resetTo(setDate)(e.target.value)}>
          {DATE_OPTS.map((d) => (
            <option key={d.v} value={d.v}>{d.label}</option>
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
                  <th>код</th>
                  <SortTh label="название" k="title" sort={sort} onSort={onSort} />
                  <SortTh label="категория" k="category" sort={sort} onSort={onSort} />
                  <SortTh label="город" k="city" sort={sort} onSort={onSort} />
                  <SortTh label="дата" k="date" sort={sort} onSort={onSort} />
                  <th>фото</th>
                  <SortTh label="статус" k="status" sort={sort} onSort={onSort} />
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.event_id} style={e.status !== "active" ? { opacity: 0.55 } : undefined}>
                    <td className="code muted">{e.code ?? "—"}</td>
                    <td>{e.title}</td>
                    <td className="muted">{e.category}</td>
                    <td className="muted">{e.city ?? "—"}</td>
                    <td className="muted">{fmtDate(e.next_date)}</td>
                    <td className="muted">{e.has_image ? "✓" : "—"}</td>
                    <td>
                      <button className="iconbtn" disabled={!!busy[e.event_id]} onClick={() => toggleStatus(e)} title={e.status === "active" ? "скрыть" : "вернуть"}>
                        {e.status === "active" ? <Badge kind="ok">active</Badge> : <Badge kind="off">{e.status}</Badge>}
                      </button>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <select
                        value={e.category}
                        disabled={!!busy[e.event_id]}
                        onChange={(ev) => reclassify(e, ev.target.value)}
                        title="сменить категорию (перебивает LLM)"
                        style={{ background: "var(--vitrine)", border: "1px solid var(--line)", color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 11, padding: "2px 4px" }}
                      >
                        {!(facets.data?.categories ?? []).includes(e.category) && <option value={e.category}>{e.category}</option>}
                        {(facets.data?.categories ?? []).map((cc) => (
                          <option key={cc} value={cc}>{cc}</option>
                        ))}
                      </select>
                    </td>
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

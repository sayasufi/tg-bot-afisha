import { useEffect, useMemo, useState } from "react";

import { SortTh } from "../components/sortable";
import { useApi } from "../lib/useApi";

type Ch = {
  username: string; title: string | null; city: string | null; ad_price: number | null;
  last_scraped_at: string | null; subscribers: number | null; avg_reach: number | null;
  er: number | null; post_price: number | null; cpm: number | null; rating: number | null;
};

const num = (n: number | null) => (n == null ? "—" : n.toLocaleString("ru-RU"));

export function Adstat() {
  const facets = useApi<{ cities: string[] }>("/adstat/facets");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [city, setCity] = useState("");
  const [minSubs, setMinSubs] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "rating", dir: "desc" });
  const [page, setPage] = useState(0);

  useEffect(() => { const t = setTimeout(() => { setQd(q); setPage(0); }, 350); return () => clearTimeout(t); }, [q]);
  const onSort = (k: string) => { setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "asc" })); setPage(0); };

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (qd.trim()) p.set("q", qd.trim());
    if (city) p.set("city", city);
    if (minSubs) p.set("min_subs", minSubs);
    p.set("sort", sort.key); p.set("dir", sort.dir);
    if (page) p.set("page", String(page));
    return `/adstat?${p.toString()}`;
  }, [qd, city, minSubs, sort, page]);

  const { data, error, loading, reload } = useApi<any>(path);
  const items: Ch[] = data?.items ?? [];
  const resetTo = (setter: (v: string) => void) => (v: string) => { setter(v); setPage(0); };
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / (data?.page_size ?? 100)));

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">реклама · каналы</h1>
          <div className="page__sub">{data ? `${total.toLocaleString("ru-RU")} каналов по фильтру` : "ресёрч рекламных TG-каналов"}</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        <input placeholder="поиск по @username / названию…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={city} onChange={(e) => resetTo(setCity)(e.target.value)}>
          <option value="">все города</option>
          {(facets.data?.cities ?? []).map((cc) => <option key={cc} value={cc}>{cc}</option>)}
        </select>
        <select value={minSubs} onChange={(e) => resetTo(setMinSubs)(e.target.value)}>
          <option value="">любой размер</option>
          <option value="1000">≥ 1 000</option>
          <option value="5000">≥ 5 000</option>
          <option value="20000">≥ 20 000</option>
          <option value="100000">≥ 100 000</option>
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
                  <th>канал</th>
                  <th>город</th>
                  <SortTh label="подписч." k="subs" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="охват" k="reach" sort={sort} onSort={onSort} className="num" />
                  <th className="num">ER</th>
                  <SortTh label="цена пост" k="price" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="CPM" k="cpm" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="рейтинг" k="rating" sort={sort} onSort={onSort} className="num" />
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.username}>
                    <td>
                      <a href={`https://t.me/${c.username}`} target="_blank" rel="noreferrer">@{c.username}</a>
                      {c.title && <div className="code muted" style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</div>}
                    </td>
                    <td className="muted">{c.city ?? "—"}</td>
                    <td className="num">{num(c.subscribers)}</td>
                    <td className="num muted">{num(c.avg_reach)}</td>
                    <td className="num muted">{c.er != null ? `${c.er.toFixed(1)}%` : "—"}</td>
                    <td className="num muted">{c.post_price != null ? `${num(Math.round(c.post_price))}₽` : "—"}</td>
                    <td className="num muted">{c.cpm != null ? `${c.cpm}₽` : "—"}</td>
                    <td className="num">{c.rating ?? "—"}</td>
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

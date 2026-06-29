import { useEffect, useMemo, useState } from "react";

import { SortTh } from "../components/sortable";
import { Badge } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

type Ch = {
  username: string; title: string | null; city: string | null; ad_price: number | null;
  last_scraped_at: string | null; subscribers: number | null; avg_reach: number | null;
  er: number | null; post_price: number | null; cpm: number | null;
  score: number | null; verdict: string | null; quality: number | null; relevance: string | null;
};

const VERDICT_KIND: Record<string, "ok" | "warn" | "down" | "off"> = { "брать": "ok", "осторожно": "warn", "мимо": "off" };

const num = (n: number | null) => (n == null ? "—" : n.toLocaleString("ru-RU"));

export function Adstat() {
  const facets = useApi<{ cities: string[]; verdicts: string[]; relevances: string[] }>("/adstat/facets");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [city, setCity] = useState("");
  const [minSubs, setMinSubs] = useState("");
  const [verdict, setVerdict] = useState("");
  const [relevance, setRelevance] = useState("");
  const [hasPrice, setHasPrice] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "score", dir: "desc" });
  const [page, setPage] = useState(0);

  useEffect(() => { const t = setTimeout(() => { setQd(q); setPage(0); }, 350); return () => clearTimeout(t); }, [q]);
  const onSort = (k: string) => { setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "asc" })); setPage(0); };

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (qd.trim()) p.set("q", qd.trim());
    if (city) p.set("city", city);
    if (minSubs) p.set("min_subs", minSubs);
    if (verdict) p.set("verdict", verdict);
    if (relevance) p.set("relevance", relevance);
    if (hasPrice) p.set("has_price", hasPrice);
    p.set("sort", sort.key); p.set("dir", sort.dir);
    if (page) p.set("page", String(page));
    return `/adstat?${p.toString()}`;
  }, [qd, city, minSubs, verdict, relevance, hasPrice, sort, page]);

  const { data, error, loading, reload } = useApi<any>(path);
  const flows = useApi<any>("/flows");
  const refreshDeploy = (flows.data?.flows ?? []).find((f: any) => f.name === "refresh-adstat-subs");
  const [refreshing, setRefreshing] = useState(false);
  const refreshSubs = async () => {
    if (!refreshDeploy) return;
    if (!window.confirm("Обновить реальные подписчики с t.me (фоновый прогон по ~600 каналам)?")) return;
    setRefreshing(true);
    try { await apiPost("/ops/run", { deployment_id: refreshDeploy.id, name: refreshDeploy.name }); }
    finally { setTimeout(() => setRefreshing(false), 2000); }
  };
  const items: Ch[] = data?.items ?? [];
  const resetTo = (setter: (v: string) => void) => (v: string) => { setter(v); setPage(0); };
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / (data?.page_size ?? 100)));

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">реклама · каналы</h1>
          <div className="page__sub">{data ? `${total.toLocaleString("ru-RU")} каналов по фильтру · подписчики из t.me/telethon` : "ресёрч рекламных TG-каналов"}</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => { setVerdict(""); setRelevance("афиша"); setHasPrice("1"); setSort({ key: "score", dir: "desc" }); setPage(0); }} title="на закупку: афиша-каналы с ценой, по нашему скору">
            топ к покупке
          </button>
          {refreshDeploy && (
            <button className="btn btn--ghost" disabled={refreshing} onClick={refreshSubs} title="фоновый прогон: подтянуть живые подписчики+охват с t.me">
              {refreshing ? "запущено…" : "обновить метрики"}
            </button>
          )}
          <button className="btn btn--ghost" onClick={reload}>обновить</button>
        </div>
      </div>

      <div className="filterbar">
        <input placeholder="поиск по @username / названию…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={city} onChange={(e) => resetTo(setCity)(e.target.value)}>
          <option value="">все города</option>
          {(facets.data?.cities ?? []).map((cc) => <option key={cc} value={cc}>{cc}</option>)}
        </select>
        <select value={verdict} onChange={(e) => resetTo(setVerdict)(e.target.value)}>
          <option value="">любой вердикт</option>
          {(facets.data?.verdicts ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <select value={relevance} onChange={(e) => resetTo(setRelevance)(e.target.value)}>
          <option value="">любая тема</option>
          {(facets.data?.relevances ?? []).map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={hasPrice} onChange={(e) => resetTo(setHasPrice)(e.target.value)}>
          <option value="">цена: любая</option>
          <option value="1">только с ценой</option>
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
                  <th>тема</th>
                  <SortTh label="подписч." k="subs" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="охват" k="reach" sort={sort} onSort={onSort} className="num" />
                  <th className="num">ER</th>
                  <SortTh label="цена пост" k="price" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="CPM" k="cpm" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="скор" k="score" sort={sort} onSort={onSort} className="num" />
                  <th>вердикт</th>
                  <th>купить</th>
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
                    <td className="muted">{c.relevance ?? "—"}</td>
                    <td className="num">{num(c.subscribers)}</td>
                    <td className="num muted">{num(c.avg_reach)}</td>
                    <td className="num muted">{c.er != null ? `${c.er.toFixed(1)}%` : "—"}</td>
                    <td className="num muted">{c.post_price != null ? `${num(Math.round(c.post_price))}₽` : "—"}</td>
                    <td className="num muted">{c.cpm != null ? `${c.cpm}₽` : "—"}</td>
                    <td className="num">{c.score ?? "—"}</td>
                    <td>{c.verdict ? <Badge kind={VERDICT_KIND[c.verdict] ?? "off"}>{c.verdict}</Badge> : "—"}</td>
                    <td><a href={`https://telega.in/channels/${c.username}/card`} target="_blank" rel="noreferrer">Telega →</a></td>
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

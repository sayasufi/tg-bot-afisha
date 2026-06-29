import { useEffect, useMemo, useState } from "react";

import { SortTh } from "../components/sortable";
import { useApi } from "../lib/useApi";

type U = {
  telegram_user_id: number;
  username: string | null;
  first_name: string | null;
  city: string | null;
  onboarded: boolean;
  notify_digest: boolean;
  notify_reminders: boolean;
  n_interests: number;
  fav_count: number;
  friend_count: number;
  created_at: string | null;
  last_active_at: string | null;
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.round(s / 60)} мин`;
  if (s < 86400) return `${Math.round(s / 3600)} ч`;
  return `${Math.round(s / 86400)} дн`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "2-digit" });
}

const YN = [
  { v: "", label: "все" },
  { v: "true", label: "да" },
  { v: "false", label: "нет" },
];

export function Users() {
  const facets = useApi<{ cities: { slug: string; name: string }[] }>("/users/facets");

  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [city, setCity] = useState("");
  const [onb, setOnb] = useState("");
  const [dig, setDig] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "active", dir: "desc" });
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
    if (onb) p.set("onboarded", onb);
    if (dig) p.set("digest", dig);
    p.set("sort", sort.key);
    p.set("dir", sort.dir);
    if (page) p.set("page", String(page));
    return `/users?${p.toString()}`;
  }, [qd, city, onb, dig, sort, page]);

  const { data, error, loading, reload } = useApi<any>(path);
  const items: U[] = data?.items ?? [];
  const resetTo = (setter: (v: string) => void) => (v: string) => {
    setter(v);
    setPage(0);
  };

  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 100;
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">пользователи</h1>
          <div className="page__sub">{data ? `${total.toLocaleString("ru-RU")} по фильтру` : "аудитория"}</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        <input placeholder="поиск по @username / имени…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={city} onChange={(e) => resetTo(setCity)(e.target.value)}>
          <option value="">все города</option>
          {(facets.data?.cities ?? []).map((c) => (
            <option key={c.slug} value={c.slug}>{c.name}</option>
          ))}
        </select>
        <select value={onb} onChange={(e) => resetTo(setOnb)(e.target.value)}>
          {YN.map((o) => <option key={o.v} value={o.v}>{o.v === "" ? "онбординг: все" : `онбординг: ${o.label}`}</option>)}
        </select>
        <select value={dig} onChange={(e) => resetTo(setDig)(e.target.value)}>
          {YN.map((o) => <option key={o.v} value={o.v}>{o.v === "" ? "дайджест: все" : `дайджест: ${o.label}`}</option>)}
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
                  <SortTh label="пользователь" k="username" sort={sort} onSort={onSort} />
                  <SortTh label="город" k="city" sort={sort} onSort={onSort} />
                  <SortTh label="избранное" k="favorites" sort={sort} onSort={onSort} className="num" />
                  <SortTh label="друзья" k="friends" sort={sort} onSort={onSort} className="num" />
                  <th className="num">интересы</th>
                  <th>дайджест</th>
                  <SortTh label="актив." k="active" sort={sort} onSort={onSort} />
                  <SortTh label="регистрация" k="created" sort={sort} onSort={onSort} />
                </tr>
              </thead>
              <tbody>
                {items.map((u) => (
                  <tr key={u.telegram_user_id} style={!u.onboarded ? { opacity: 0.55 } : undefined}>
                    <td>
                      <div>{u.username ? `@${u.username}` : u.first_name || "—"}</div>
                      <div className="code muted">{u.telegram_user_id}{u.username && u.first_name ? ` · ${u.first_name}` : ""}{!u.onboarded ? " · не онбордился" : ""}</div>
                    </td>
                    <td className="muted">{u.city ?? "—"}</td>
                    <td className="num">{u.fav_count}</td>
                    <td className="num">{u.friend_count}</td>
                    <td className="num muted">{u.n_interests}</td>
                    <td className="muted">{u.notify_digest ? "✓" : "—"}</td>
                    <td className="muted">{ago(u.last_active_at)}</td>
                    <td className="muted">{fmtDate(u.created_at)}</td>
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

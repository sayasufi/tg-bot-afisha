import { useMemo, useState } from "react";

import { SortTh, useSort } from "../components/sortable";
import { Badge, fmtNum } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

type Ch = {
  channel_id: number;
  username: string;
  city: string | null;
  city_id: number;
  is_active: boolean;
  venue_name: string | null;
  venue_address: string | null;
  subscribers: number | null;
  updated_at: string | null;
};

const SORT_GET = (c: Ch, k: string): any => {
  switch (k) {
    case "city": return c.city;
    case "subs": return c.subscribers;
    case "venue": return c.venue_name;
    case "active": return c.is_active ? 0 : 1;
    default: return c.username.toLowerCase();
  }
};

export function Channels() {
  const { data, error, loading, reload } = useApi<{ items: Ch[]; total: number }>("/venue-channels", 60000);
  const all = data?.items ?? [];

  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [bound, setBound] = useState("");
  const [showDead, setShowDead] = useState(false);

  const cityOpts = useMemo(() => {
    const m = new Map<number, string>();
    all.forEach((c) => {
      if (c.city) m.set(c.city_id, c.city);
    });
    return [...m.entries()].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [all]);

  const filtered = useMemo(
    () =>
      all.filter(
        (c) =>
          (!q ||
            c.username.toLowerCase().includes(q.toLowerCase()) ||
            (c.venue_name ?? "").toLowerCase().includes(q.toLowerCase())) &&
          (!city || String(c.city_id) === city) &&
          (!bound || (bound === "bound" ? !!c.venue_name : !c.venue_name)) &&
          (showDead || c.is_active)
      ),
    [all, q, city, bound, showDead]
  );

  const { sorted, sort, onSort } = useSort(filtered, SORT_GET, { key: "subs", dir: "desc" });
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  const toggle = async (c: Ch) => {
    setBusy((b) => ({ ...b, [c.channel_id]: true }));
    try {
      await apiPost(`/venue-channels/${c.channel_id}/toggle`, { active: !c.is_active });
      reload();
    } finally {
      setBusy((b) => ({ ...b, [c.channel_id]: false }));
    }
  };

  const rebind = async (c: Ch) => {
    const vn = window.prompt("Площадка (пусто = общий канал):", c.venue_name ?? "");
    if (vn === null) return;
    const va = window.prompt("Адрес площадки:", c.venue_address ?? "") ?? "";
    await apiPost(`/venue-channels/${c.channel_id}/bind`, { venue_name: vn, venue_address: va });
    reload();
  };

  const [newU, setNewU] = useState("");
  const [newCity, setNewCity] = useState("");
  const [adding, setAdding] = useState(false);
  const add = async () => {
    if (!newU.trim() || !newCity) return;
    setAdding(true);
    try {
      await apiPost("/venue-channels", { username: newU.trim(), city_id: Number(newCity) });
      setNewU("");
      reload();
    } finally {
      setAdding(false);
    }
  };

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">tg-каналы</h1>
          <div className="page__sub">{data ? `${data.total} каналов площадок` : "каналы площадок"}</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        <input placeholder="добавить канал: username" value={newU} onChange={(e) => setNewU(e.target.value)} />
        <select value={newCity} onChange={(e) => setNewCity(e.target.value)}>
          <option value="">город…</option>
          {cityOpts.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <button className="btn" disabled={adding || !newU.trim() || !newCity} onClick={add}>
          {adding ? "…" : "добавить"}
        </button>
      </div>

      <div className="filterbar">
        <input placeholder="поиск: канал или площадка…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={city} onChange={(e) => setCity(e.target.value)}>
          <option value="">все города</option>
          {cityOpts.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select value={bound} onChange={(e) => setBound(e.target.value)}>
          <option value="">с привязкой и без</option>
          <option value="bound">привязан к площадке</option>
          <option value="general">общий</option>
        </select>
        <label style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: 12, color: "var(--ink-dim)" }}>
          <input type="checkbox" checked={showDead} onChange={(e) => setShowDead(e.target.checked)} style={{ minWidth: 0 }} />
          показать выключенные
        </label>
        <span className="filter-count">показано {sorted.length}</span>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <SortTh label="канал" k="username" sort={sort} onSort={onSort} />
                <SortTh label="город" k="city" sort={sort} onSort={onSort} />
                <SortTh label="подписчики" k="subs" sort={sort} onSort={onSort} className="num" />
                <SortTh label="площадка" k="venue" sort={sort} onSort={onSort} />
                <SortTh label="активен" k="active" sort={sort} onSort={onSort} />
                <th />
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.channel_id}>
                  <td className="code">@{c.username}</td>
                  <td className="muted">{c.city ?? "—"}</td>
                  <td className="num">{c.subscribers == null ? "—" : fmtNum(c.subscribers)}</td>
                  <td>{c.venue_name ?? <span className="muted">общий</span>}</td>
                  <td>
                    <button className="iconbtn" disabled={!!busy[c.channel_id]} onClick={() => toggle(c)}>
                      {c.is_active ? <Badge kind="ok">вкл</Badge> : <Badge kind="off">выкл</Badge>}
                    </button>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button className="iconbtn" onClick={() => rebind(c)}>привязка</button>
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

import { useMemo, useState } from "react";

import { Badge, fmtNum } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

type Channel = {
  channel_id: number;
  username: string;
  city_id: number;
  city: string | null;
  is_active: boolean;
  venue_name: string | null;
  venue_address: string | null;
  subscribers: number | null;
  updated_at: string | null;
};

type CityOpt = { city_id: number; name: string; channels: number };

export function Channels() {
  // Управляемые фильтры → query-параметры пути (useApi перезапрашивает при смене path).
  const [q, setQ] = useState("");
  const [cityId, setCityId] = useState<string>("");
  const [dead, setDead] = useState(false);

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (cityId) p.set("city_id", cityId);
    if (dead) p.set("dead", "true");
    const qs = p.toString();
    return `/venue-channels${qs ? `?${qs}` : ""}`;
  }, [q, cityId, dead]);

  const { data, error, loading, reload } = useApi<{ total: number; items: Channel[] }>(path, 30000);
  const cities = useApi<{ items: CityOpt[] }>("/venue-channels/cities", 60000);
  const cityOpts: CityOpt[] = cities.data?.items ?? [];

  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const setRowBusy = (id: number, v: boolean) => setBusy((b) => ({ ...b, [id]: v }));

  const toggle = async (c: Channel) => {
    setRowBusy(c.channel_id, true);
    try {
      await apiPost(`/venue-channels/${c.channel_id}/toggle`, { active: !c.is_active });
      reload();
    } finally {
      setRowBusy(c.channel_id, false);
    }
  };

  const bind = async (c: Channel) => {
    const name = window.prompt("название площадки (пусто = общий канал, без привязки):", c.venue_name ?? "");
    if (name === null) return;
    const addr = window.prompt("адрес площадки (опционально):", c.venue_address ?? "");
    if (addr === null) return;
    setRowBusy(c.channel_id, true);
    try {
      await apiPost(`/venue-channels/${c.channel_id}/bind`, { venue_name: name, venue_address: addr });
      reload();
    } finally {
      setRowBusy(c.channel_id, false);
    }
  };

  // Форма добавления.
  const [addUser, setAddUser] = useState("");
  const [addCity, setAddCity] = useState<string>("");
  const [addVenue, setAddVenue] = useState("");
  const [addAddr, setAddAddr] = useState("");
  const [adding, setAdding] = useState(false);
  const [addErr, setAddErr] = useState<string | null>(null);

  const add = async () => {
    setAddErr(null);
    if (!addUser.trim()) {
      setAddErr("укажите username");
      return;
    }
    if (!addCity) {
      setAddErr("выберите город");
      return;
    }
    setAdding(true);
    try {
      await apiPost("/venue-channels", {
        username: addUser,
        city_id: Number(addCity),
        venue_name: addVenue.trim() || undefined,
        venue_address: addAddr.trim() || undefined,
      });
      setAddUser("");
      setAddVenue("");
      setAddAddr("");
      reload();
      cities.reload();
    } catch (e: any) {
      setAddErr(e?.message ?? "не удалось добавить");
    } finally {
      setAdding(false);
    }
  };

  const items: Channel[] = data?.items ?? [];

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">tg-каналы</h1>
          <div className="page__sub">
            каналы площадок · источник telegram-событий · всего {fmtNum(data?.total)}
            {data && items.length >= 200 ? " (показаны 200)" : ""}
          </div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {/* фильтры */}
      <div className="section__title">фильтр</div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <input
          className="login__input"
          placeholder="поиск по @username или площадке…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select className="login__input" value={cityId} onChange={(e) => setCityId(e.target.value)}>
          <option value="">все города</option>
          {cityOpts.map((c) => (
            <option key={c.city_id} value={String(c.city_id)}>
              {c.name} ({c.channels})
            </option>
          ))}
        </select>
        <label className="muted" style={{ display: "inline-flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={dead} onChange={(e) => setDead(e.target.checked)} />
          только мёртвые
        </label>
      </div>

      {/* добавить канал */}
      <div className="section__title">добавить канал</div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
        <input
          className="login__input"
          placeholder="@username"
          value={addUser}
          onChange={(e) => setAddUser(e.target.value)}
          style={{ minWidth: 180 }}
        />
        <select className="login__input" value={addCity} onChange={(e) => setAddCity(e.target.value)}>
          <option value="">— город —</option>
          {cityOpts.map((c) => (
            <option key={c.city_id} value={String(c.city_id)}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          className="login__input"
          placeholder="площадка (опц.)"
          value={addVenue}
          onChange={(e) => setAddVenue(e.target.value)}
          style={{ minWidth: 160 }}
        />
        <input
          className="login__input"
          placeholder="адрес (опц.)"
          value={addAddr}
          onChange={(e) => setAddAddr(e.target.value)}
          style={{ minWidth: 160 }}
        />
        <button className="btn" disabled={adding} onClick={add}>
          {adding ? "…" : "добавить"}
        </button>
      </div>
      {addErr && <div className="state state--err" style={{ marginBottom: 10 }}>{addErr}</div>}

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <th>username</th>
                <th>город</th>
                <th className="num">подписчики</th>
                <th>площадка</th>
                <th>статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.channel_id}>
                  <td className="code">@{c.username}</td>
                  <td className="muted">{c.city ?? `#${c.city_id}`}</td>
                  <td className="num">{fmtNum(c.subscribers)}</td>
                  <td>
                    {c.venue_name ? (
                      <span>
                        {c.venue_name}
                        {c.venue_address && <div className="muted" style={{ fontSize: 12 }}>{c.venue_address}</div>}
                      </span>
                    ) : (
                      <span className="muted">— общий</span>
                    )}
                  </td>
                  <td>
                    <Badge kind={c.is_active ? "ok" : "off"}>{c.is_active ? "активен" : "мёртв"}</Badge>
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="iconbtn" disabled={!!busy[c.channel_id]} onClick={() => bind(c)}>
                      привязка
                    </button>
                    <button
                      className="iconbtn"
                      disabled={!!busy[c.channel_id]}
                      onClick={() => toggle(c)}
                      style={{ marginLeft: 6 }}
                    >
                      {c.is_active ? "выключить" : "включить"}
                    </button>
                  </td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 18 }}>
                    ничего не найдено
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

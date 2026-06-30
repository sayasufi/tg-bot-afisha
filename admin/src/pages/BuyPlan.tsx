import { useMemo, useState } from "react";

import { Badge, StatCard, fmtNum } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

const V_KIND: Record<string, "ok" | "warn" | "down" | "off"> = { "брать": "ok", "осторожно": "warn", "мимо": "down" };

export function BuyPlan() {
  const [city, setCity] = useState("");
  const { data, loading, error, reload } = useApi<any>(`/buy-plan${city ? `?city=${encodeURIComponent(city)}` : ""}`, 30000);
  const items: any[] = data?.items ?? [];
  const botUser = data?.bot_username || "okrestmap_bot";
  const [budget, setBudget] = useState("50000");
  const [added, setAdded] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState("");

  const cities = useMemo(() => Array.from(new Set(items.map((i) => i.city).filter(Boolean))).sort(), [items]);

  // Жадная раскладка: лучшие по скору первыми, добавляем пока влезает в бюджет (0 = без ограничения).
  const { plan, spent, reach, planCities } = useMemo(() => {
    const b = Number(budget) || 0;
    const sel = new Set<string>();
    let sp = 0, rc = 0; const cs = new Set<string>();
    for (const it of items) {
      if (!it.price) continue;
      if (b === 0 || sp + it.price <= b) { sel.add(it.username); sp += it.price; rc += it.reach || 0; if (it.city) cs.add(it.city); }
    }
    return { plan: sel, spent: sp, reach: rc, planCities: cs };
  }, [items, budget]);

  const adLink = (u: string) => `https://t.me/${botUser}?startapp=src_${u}`;
  const copy = (u: string) => { try { navigator.clipboard?.writeText(adLink(u)); } catch { /* noop */ } };
  const addBuy = async (it: any) => {
    setBusy(it.username);
    try {
      await apiPost("/buys", { channel_username: it.username, price: it.price, note: "из плана закупки" });
      setAdded((a) => ({ ...a, [it.username]: true }));
    } finally { setBusy(""); }
  };

  const b = Number(budget) || 0;

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">план закупки</h1>
          <div className="page__sub">{items.length} каналов к закупке (брать/осторожно, с ценой) · задай бюджет → лучшие по скору в рамках суммы</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="compose" style={{ marginBottom: 16 }}>
        <div className="compose__row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="fld" style={{ minWidth: 180 }}>бюджет, ₽ (0 = без лимита)
            <input type="number" min={0} step={5000} value={budget} onChange={(e) => setBudget(e.target.value)} />
          </label>
          <label className="fld" style={{ minWidth: 180 }}>город
            <select value={city} onChange={(e) => setCity(e.target.value)} style={{ height: 36 }}>
              <option value="">все города</option>
              {cities.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="statgrid">
        <StatCard num={`${plan.size}`} label="каналов в плане" sub={`из ${items.length}`} accent />
        <StatCard num={`${spent.toLocaleString("ru-RU")}₽`} label="стоимость плана" sub={b ? `из ${b.toLocaleString("ru-RU")}₽` : "без лимита"} tone={b && spent > b ? "warn" : undefined} />
        <StatCard num={fmtNum(reach)} label="суммарный охват" sub="прогноз показов/пост" />
        <StatCard num={`${planCities.size}`} label="городов покрыто" sub={planCities.size ? Array.from(planCities).slice(0, 3).join(", ") : "—"} />
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr><th>#</th><th>канал</th><th>скор</th><th className="num">подписч.</th><th className="num">ERR</th><th className="num">реакц.</th><th className="num">CPM</th><th className="num">цена</th><th className="num">привёл</th><th /></tr>
            </thead>
            <tbody>
              {items.map((it, i) => {
                const inPlan = plan.has(it.username);
                return (
                  <tr key={it.username} style={inPlan ? { background: "color-mix(in srgb, var(--acid) 7%, transparent)" } : { opacity: 0.6 }}>
                    <td className="muted">{inPlan ? i + 1 : "—"}</td>
                    <td>
                      <a href={`https://t.me/${it.username}`} target="_blank" rel="noreferrer">@{it.username}</a>
                      {it.city ? <span className="muted" style={{ marginLeft: 6, fontSize: 11 }}>{it.city}</span> : null}
                    </td>
                    <td><span style={{ fontWeight: 600 }}>{it.score}</span> <Badge kind={V_KIND[it.verdict] || "off"}>{it.verdict}</Badge></td>
                    <td className="num">{fmtNum(it.subscribers)}</td>
                    <td className="num muted">{it.err != null ? `${it.err}%` : "—"}</td>
                    <td className="num muted">{it.rrate != null ? `${it.rrate}%` : "—"}</td>
                    <td className="num muted">{it.cpm != null ? `${it.cpm}₽` : "—"}</td>
                    <td className="num">{it.price ? `${it.price.toLocaleString("ru-RU")}₽` : "—"}</td>
                    <td className="num" style={it.acquired ? { color: "var(--acid)", fontWeight: 600 } : undefined}>{it.acquired || 0}</td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      <button className="iconbtn" onClick={() => copy(it.username)} title={adLink(it.username)}>📋</button>
                      <button className="iconbtn" disabled={busy === it.username || added[it.username]} onClick={() => addBuy(it)} style={{ marginLeft: 4 }}>
                        {added[it.username] ? "✓ в закупках" : busy === it.username ? "…" : "+ закупка"}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!items.length && <tr><td colSpan={10} className="muted">нет каналов с вердиктом брать/осторожно и ценой — добери цены (Реклама → обновить) или дождись скоринга</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

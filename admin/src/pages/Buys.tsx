import { useState } from "react";

import { Badge, StatCard, fmtNum } from "../components/ui";
import { apiDelete, apiPatch, apiPost } from "../lib/api";
import { useMutate } from "../lib/mutate";
import { useApi } from "../lib/useApi";

const STATUSES = [
  { v: "planned", label: "запланирована" },
  { v: "paid", label: "оплачена" },
  { v: "live", label: "вышла" },
  { v: "done", label: "завершена" },
  { v: "cancelled", label: "отменена" },
];
const ST_KIND: Record<string, "ok" | "warn" | "down" | "off"> = {
  planned: "off", paid: "warn", live: "warn", done: "ok", cancelled: "down",
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function Buys() {
  const { data, loading, error, reload } = useApi<any>("/buys", 15000);
  const items: any[] = data?.items ?? [];
  const botUser = data?.bot_username || "okrestmap_bot";
  const adLink = (tag: string) => `https://t.me/${botUser}?startapp=src_${tag}`;
  const copy = (tag: string) => { try { navigator.clipboard?.writeText(adLink(tag)); } catch { /* noop */ } };

  const [f, setF] = useState({ channel: "", src_tag: "", price: "", ad_at: "", note: "" });
  const [busy, setBusy] = useState(false);
  const mutate = useMutate();

  const add = async () => {
    if (!f.channel.trim()) return;
    setBusy(true);
    try {
      const ok = await mutate(() => apiPost("/buys", {
        channel_username: f.channel.trim(),
        src_tag: f.src_tag.trim() || undefined,
        price: f.price ? Number(f.price) : undefined,
        ad_at: f.ad_at ? new Date(f.ad_at).toISOString() : undefined,
        note: f.note.trim() || undefined,
      }));
      if (ok !== undefined) setF({ channel: "", src_tag: "", price: "", ad_at: "", note: "" });
      reload();
    } finally { setBusy(false); }
  };
  const setStatus = async (id: string, status: string) => { await mutate(() => apiPatch(`/buys/${id}`, { status })); reload(); };
  const del = async (b: any) => {
    const warn = b.acquired ? ` Внимание: ${b.acquired} приведённых юзеров потеряют привязку к этой закупке (лучше статус «отменена»).` : "";
    if (window.confirm(`Удалить закупку @${b.channel_username}?${warn}`)) { await mutate(() => apiDelete(`/buys/${b.id}`)); reload(); }
  };

  const sum = data?.summary;

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">закупки рекламы</h1>
          <div className="page__sub">{items.length} размещений · учёт цены/времени/статуса + ROI по каналам</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {sum && (
        <div className="statgrid">
          <StatCard num={`${(sum.spent || 0).toLocaleString("ru-RU")}₽`} label="потрачено" sub="без отменённых" accent />
          <StatCard num={fmtNum(sum.came)} label="пришло" sub="по рекл. ссылкам" />
          <StatCard num={fmtNum(sum.retained)} label="удержано" sub="активны спустя 2+ дня" tone={sum.came && !sum.retained ? "warn" : undefined} />
          <StatCard num={sum.cpv != null ? `${sum.cpv}₽` : "—"} label="CPV" sub="цена за пришедшего" />
          <StatCard num={sum.cpr != null ? `${sum.cpr}₽` : "—"} label="CPR" sub="цена за удержанного" />
        </div>
      )}

      <div className="compose" style={{ marginBottom: 18 }}>
        <div className="section__title" style={{ marginTop: 0 }}>новая закупка</div>
        <div className="compose__row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="fld" style={{ flex: 2, minWidth: 160 }}>канал (@username)
            <input value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })} placeholder="afisha22" />
          </label>
          <label className="fld" style={{ flex: 2, minWidth: 160 }}>метка ссылки (опц., по умолч. = канал)
            <input value={f.src_tag} onChange={(e) => setF({ ...f, src_tag: e.target.value })} placeholder="afisha22_jul" />
          </label>
          <label className="fld" style={{ flex: 1, minWidth: 100 }}>цена, ₽
            <input type="number" min={0} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} placeholder="5000" />
          </label>
          <label className="fld" style={{ flex: 2, minWidth: 180 }}>когда выходит
            <input type="datetime-local" value={f.ad_at} onChange={(e) => setF({ ...f, ad_at: e.target.value })} />
          </label>
          <label className="fld" style={{ flex: 3, minWidth: 160 }}>заметка
            <input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="формат, договорённости…" />
          </label>
          <button className="btn" disabled={busy || !f.channel.trim()} onClick={add} style={{ height: 36 }}>{busy ? "…" : "добавить"}</button>
        </div>
        <div className="chart-hint" style={{ marginTop: 8 }}>
          Ссылку для рекламы (<span className="code">t.me/{botUser}?startapp=src_&lt;метка&gt;</span>) кладёшь в пост — пришедшие по ней
          юзеры считаются как «привёл» именно этой закупки. Кнопка 📋 в таблице копирует готовую ссылку.
        </div>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr><th>канал</th><th>ссылка</th><th className="num">цена</th><th>когда</th><th>статус</th><th className="num">привёл</th><th className="num">удержан</th><th className="num">CPV</th><th className="num">CPR</th><th>заметка</th><th /></tr>
            </thead>
            <tbody>
              {items.map((b) => (
                <tr key={b.id}>
                  <td>
                    <a href={`https://t.me/${b.channel_username}`} target="_blank" rel="noreferrer">@{b.channel_username}</a>
                    <div className="code muted">src_{b.src_tag}</div>
                  </td>
                  <td><button className="iconbtn" onClick={() => copy(b.src_tag)} title={adLink(b.src_tag)}>📋 копир.</button></td>
                  <td className="num">{b.price != null ? `${b.price.toLocaleString("ru-RU")}₽` : "—"}</td>
                  <td className="muted">{when(b.ad_at)}</td>
                  <td>
                    <select value={b.status} onChange={(e) => setStatus(b.id, e.target.value)} style={{ background: "var(--vitrine)", border: "1px solid var(--line)", color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 11, padding: "3px 6px" }}>
                      {STATUSES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                    </select>
                  </td>
                  <td className="num" style={b.acquired ? { color: "var(--acid)", fontWeight: 600 } : undefined}>
                    {b.acquired || 0}
                    {b.acquired ? <span className="muted" style={{ fontWeight: 400 }}> ({b.onboarded}✓/{b.active7}akt)</span> : null}
                  </td>
                  <td className="num" style={b.retained ? { color: "var(--acid)", fontWeight: 600 } : undefined} title="активны спустя 2+ дня после захода">{b.retained || 0}</td>
                  <td className="num muted">{b.cpv != null ? `${b.cpv}₽` : "—"}</td>
                  <td className="num muted" title="цена за удержанного — главная ROI-метрика">{b.cpr != null ? `${b.cpr}₽` : "—"}</td>
                  <td className="muted" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.note ?? "—"}</td>
                  <td style={{ textAlign: "right" }}><button className="iconbtn" onClick={() => del(b)}>✕</button></td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan={11} className="muted">пока нет закупок — добавь первую выше</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

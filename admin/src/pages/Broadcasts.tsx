import { useEffect, useMemo, useState } from "react";

import { Badge, StatCard, fmtNum } from "../components/ui";
import { apiPatch, apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

const STATUS_KIND: Record<string, "ok" | "warn" | "down" | "off"> = {
  draft: "off", scheduled: "warn", sending: "warn", sent: "ok", cancelled: "off",
};
const STATUS_LABEL: Record<string, string> = {
  draft: "черновик", scheduled: "запланирована", sending: "идёт", sent: "отправлена", cancelled: "отменена",
};
const AUD_KINDS = [
  { v: "opted_in", label: "подписаны на дайджест" },
  { v: "all", label: "все (кто не отписался)" },
  { v: "city", label: "по городам" },
  { v: "active_since", label: "активны за N дней" },
];

type Form = {
  id: string | null;
  title: string; body: string; image_url: string;
  button_label: string; button_url: string;
  aud_kind: string; cities: string[]; since_days: number;
  test_sent: boolean; status: string;
  sched: "now" | "at_utc"; scheduled_at: string;
};
const EMPTY: Form = {
  id: null, title: "", body: "", image_url: "", button_label: "", button_url: "",
  aud_kind: "opted_in", cities: [], since_days: 7, test_sent: false, status: "draft",
  sched: "now", scheduled_at: "",
};

export function Broadcasts() {
  const campaigns = useApi<any>("/broadcast/campaigns", 8000);
  const recips = useApi<any>("/broadcast/recipients", 60000);
  const facets = useApi<{ cities: { slug: string; name: string }[] }>("/users/facets");

  const [f, setF] = useState<Form>(EMPTY);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [dry, setDry] = useState<{ count: number; by_city: Record<string, number> } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [legacyBusy, setLegacyBusy] = useState<string | null>(null);

  const audience = useMemo(() => {
    const a: any = { kind: f.aud_kind };
    if (f.aud_kind === "city") a.cities = f.cities;
    if (f.aud_kind === "active_since") a.since_days = f.since_days;
    return a;
  }, [f.aud_kind, f.cities, f.since_days]);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(async () => {
      try { setDry(await apiPost("/broadcast/dry-run", { audience })); } catch { setDry(null); }
    }, 400);
    return () => clearTimeout(t);
  }, [audience, open]);

  const update = (patch: Partial<Form>) => setF((s) => ({ ...s, ...patch }));

  const startNew = () => { setF(EMPTY); setOpen(true); setConfirm(false); setMsg(null); };
  const loadCampaign = (c: any) => {
    setF({
      id: c.id, title: c.title, body: c.body, image_url: c.image_url || "",
      button_label: c.button_label || "", button_url: c.button_url || "",
      aud_kind: c.audience?.kind || "opted_in", cities: c.audience?.cities || [], since_days: c.audience?.since_days || 7,
      test_sent: !!c.test_sent_at, status: c.status,
      sched: c.schedule_kind === "at_utc" ? "at_utc" : "now", scheduled_at: c.scheduled_at ? c.scheduled_at.slice(0, 16) : "",
    });
    setOpen(true); setConfirm(false); setMsg(null);
  };

  const draftPayload = () => ({
    title: f.title, body: f.body, image_url: f.image_url,
    button_label: f.button_label, button_url: f.button_url, audience,
  });

  const saveDraft = async (): Promise<string | null> => {
    let id = f.id;
    if (id) await apiPatch(`/broadcast/campaigns/${id}`, draftPayload());
    else { const r = await apiPost("/broadcast/campaigns", draftPayload()); id = r.id; update({ id }); }
    campaigns.reload();
    return id;
  };

  const onSave = async () => {
    setBusy("save"); setMsg(null);
    try { await saveDraft(); setMsg("✓ черновик сохранён"); }
    catch (e: any) { setMsg(`ошибка: ${e.message}`); }
    finally { setBusy(null); }
  };

  const test = async () => {
    setBusy("test"); setMsg(null);
    try {
      const id = await saveDraft();
      const r = await apiPost(`/broadcast/campaigns/${id}/test`);
      if (r.sent === 1) { update({ test_sent: true }); setMsg(`✓ тест ушёл на ${r.to} — проверь Telegram, потом подтверди`); }
      else setMsg(`тест не отправился (sent=${r.sent}) — проверь HTML-разметку и ссылку кнопки`);
    } catch (e: any) { setMsg(`ошибка теста: ${e.message}`); }
    finally { setBusy(null); campaigns.reload(); }
  };

  const send = async () => {
    if (!dry) return;
    setBusy("send"); setMsg(null);
    try {
      const id = await saveDraft();
      if (f.sched === "now") {
        const r = await apiPost(`/broadcast/campaigns/${id}/send-now`, { confirm: true, expected_count: dry.count });
        setMsg(`✓ ${r.note || "запущено"}`);
      } else {
        const at = new Date(f.scheduled_at).toISOString();
        const r = await apiPost(`/broadcast/campaigns/${id}/schedule`, { kind: "at_utc", scheduled_at: at, confirm: true, expected_count: dry.count });
        setMsg(`✓ запланировано на ${new Date(r.scheduled_at).toLocaleString("ru-RU")}`);
      }
      setOpen(false); campaigns.reload();
    } catch (e: any) { setMsg(`не отправлено: ${e.message}`); }
    finally { setBusy(null); }
  };

  const cancel = async (c: any) => {
    if (!window.confirm(`Отменить кампанию «${c.title}»?`)) return;
    try { await apiPost(`/broadcast/campaigns/${c.id}/cancel`); campaigns.reload(); }
    catch (e: any) { window.alert(e.message); }
  };

  const legacyTest = async (kind: "digest" | "reminder") => {
    setLegacyBusy(kind);
    try {
      const r = await apiPost("/broadcast/test", { kind });
      setMsg(r.sent ? `✓ ${kind === "digest" ? "дайджест" : "напоминание"} → тест-аккаунт (${r.to})` : "отправлено 0 — нет контента");
    } catch (e: any) { setMsg(`ошибка: ${e.message}`); }
    finally { setLegacyBusy(null); }
  };

  const canSend = f.test_sent && confirm && (f.sched === "now" || !!f.scheduled_at) && !!f.title.trim() && !!f.body.trim();
  const items: any[] = campaigns.data?.items ?? [];
  const r = recips.data;

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">рассылки</h1>
          <div className="page__sub">кастомные кампании · отправка по клику или по времени · тест строго себе</div>
        </div>
        <button className="btn" onClick={startNew}>+ новая кампания</button>
      </div>

      {open && (
        <div className="compose">
          <div className="section__title">{f.id ? "редактирование" : "новая кампания"} {f.status !== "draft" && <Badge kind={STATUS_KIND[f.status]}>{STATUS_LABEL[f.status]}</Badge>}</div>
          <div className="compose__grid">
            <div className="compose__main">
              <label className="fld">заголовок (для админки)
                <input value={f.title} onChange={(e) => update({ title: e.target.value })} placeholder="напр. Подборка на выходные" />
              </label>
              <label className="fld">текст сообщения (HTML: &lt;b&gt; &lt;i&gt; &lt;a href&gt;)
                <textarea rows={6} value={f.body} onChange={(e) => update({ body: e.target.value, test_sent: false })} placeholder="Что отправляем пользователям…" />
              </label>
              <label className="fld">картинка (URL, опц.)
                <input value={f.image_url} onChange={(e) => update({ image_url: e.target.value, test_sent: false })} placeholder="https://…" />
              </label>
              <div className="compose__row">
                <label className="fld" style={{ flex: 1 }}>кнопка — текст
                  <input value={f.button_label} onChange={(e) => update({ button_label: e.target.value, test_sent: false })} placeholder="Открыть афишу" />
                </label>
                <label className="fld" style={{ flex: 2 }}>кнопка — ссылка (https)
                  <input value={f.button_url} onChange={(e) => update({ button_url: e.target.value, test_sent: false })} placeholder="https://t.me/okrestmap_bot?startapp=…" />
                </label>
              </div>
            </div>

            <div className="compose__side">
              <div className="fld">аудитория
                <select value={f.aud_kind} onChange={(e) => update({ aud_kind: e.target.value })}>
                  {AUD_KINDS.map((a) => <option key={a.v} value={a.v}>{a.label}</option>)}
                </select>
              </div>
              {f.aud_kind === "city" && (
                <div className="fld">города (мультивыбор)
                  <select multiple value={f.cities} style={{ height: 110 }}
                    onChange={(e) => update({ cities: Array.from(e.target.selectedOptions, (o) => o.value) })}>
                    {(facets.data?.cities ?? []).map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
                  </select>
                </div>
              )}
              {f.aud_kind === "active_since" && (
                <label className="fld">активны за дней
                  <input type="number" min={1} max={365} value={f.since_days} onChange={(e) => update({ since_days: parseInt(e.target.value, 10) || 7 })} />
                </label>
              )}
              <div className="dryrun">
                получателей: <b>{dry ? dry.count.toLocaleString("ru-RU") : "…"}</b>
                {dry && Object.keys(dry.by_city).length > 1 && (
                  <div className="dryrun__cities">{Object.entries(dry.by_city).map(([c, n]) => `${c}: ${n}`).join(" · ")}</div>
                )}
              </div>

              <div className="fld">когда
                <select value={f.sched} onChange={(e) => update({ sched: e.target.value as any })}>
                  <option value="now">сейчас (по клику)</option>
                  <option value="at_utc">в дату/время</option>
                </select>
              </div>
              {f.sched === "at_utc" && (
                <label className="fld">дата и время (ваш часовой пояс)
                  <input type="datetime-local" value={f.scheduled_at} onChange={(e) => update({ scheduled_at: e.target.value })} />
                </label>
              )}
            </div>
          </div>

          <div className="bcast-note">
            Боевая отправка возможна только после <b>теста себе</b> и явного подтверждения. Опт-аут
            (<span className="code">notify_broadcasts</span>) уважается всегда. Тест уходит строго на тест-аккаунт.
          </div>

          <div className="compose__actions">
            <button className="btn btn--ghost" disabled={!!busy} onClick={onSave}>{busy === "save" ? "…" : "сохранить черновик"}</button>
            <button className="btn btn--ghost" disabled={!!busy || !f.title.trim() || !f.body.trim()} onClick={test}>{busy === "test" ? "отправляю…" : "тест себе"}</button>
            <label className="confirm-chk">
              <input type="checkbox" checked={confirm} disabled={!f.test_sent} onChange={(e) => setConfirm(e.target.checked)} />
              я проверил тест и подтверждаю боевую отправку
            </label>
            <button className="btn" disabled={!!busy || !canSend} onClick={send}>
              {busy === "send" ? "…" : f.sched === "now" ? `отправить сейчас (${dry?.count ?? 0})` : "запланировать"}
            </button>
            <button className="btn btn--ghost" onClick={() => setOpen(false)}>закрыть</button>
          </div>
          {msg && <div className="bcast-msg">{msg}</div>}
        </div>
      )}

      <div className="section__title">кампании</div>
      {campaigns.error && <div className="state state--err">ошибка: {campaigns.error}</div>}
      <div className="tablewrap">
        <table className="table">
          <thead>
            <tr><th>кампания</th><th>статус</th><th>когда</th><th className="num">отправлено</th><th className="num">ошибок</th><th /></tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td>{c.title}<div className="code muted">{(c.audience?.kind) || "—"}</div></td>
                <td><Badge kind={STATUS_KIND[c.status] ?? "off"}>{STATUS_LABEL[c.status] ?? c.status}</Badge></td>
                <td className="muted">{c.schedule_kind === "at_utc" && c.scheduled_at ? new Date(c.scheduled_at).toLocaleString("ru-RU") : c.status === "sent" ? "—" : "по клику"}</td>
                <td className="num">{c.sent_count}</td>
                <td className="num muted">{c.failed_count}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="iconbtn" onClick={() => loadCampaign(c)}>{c.status === "draft" ? "править" : "открыть"}</button>
                  {(c.status === "draft" || c.status === "scheduled") && <button className="iconbtn" onClick={() => cancel(c)}>отменить</button>}
                </td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan={6} className="muted">пока нет кампаний — нажми «+ новая кампания»</td></tr>}
          </tbody>
        </table>
      </div>

      {r && (
        <>
          <div className="section__title">аудитория и тесты дайджеста/напоминаний</div>
          <div className="statgrid">
            <StatCard num={fmtNum(r.total)} label="всего пользователей" accent />
            <StatCard num={fmtNum(r.digest_optin)} label="подписаны на дайджест" />
            <StatCard num={fmtNum(r.reminder_optin)} label="напоминания не отключали" />
            <StatCard num={fmtNum(r.active_7d)} label="активны за 7д" />
          </div>
          <div className="bcast-actions" style={{ marginTop: 12 }}>
            <button className="btn btn--ghost" disabled={!r.test_user_id || !!legacyBusy} onClick={() => legacyTest("digest")}>{legacyBusy === "digest" ? "…" : "тест дайджеста себе"}</button>
            <button className="btn btn--ghost" disabled={!r.test_user_id || !!legacyBusy} onClick={() => legacyTest("reminder")}>{legacyBusy === "reminder" ? "…" : "тест напоминания себе"}</button>
          </div>
        </>
      )}
    </div>
  );
}

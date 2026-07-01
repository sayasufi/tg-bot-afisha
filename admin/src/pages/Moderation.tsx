import { useEffect, useMemo, useState } from "react";

import { apiPost, ApiError } from "../lib/api";
import { useApi } from "../lib/useApi";

type Sub = {
  submission_id: string;
  kind: string;
  status: string;
  data: Record<string, any>;
  checks: Record<string, any> | null;
  submitted_by: number;
  submitted_username: string | null;
  city_slug: string | null;
  reject_code: string | null;
  created_at: string | null;
};

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "needs_review", label: "на модерации" },
  { key: "approved", label: "одобрено" },
  { key: "ingested", label: "на карте" },
  { key: "rejected", label: "отклонено" },
  { key: "", label: "все" },
];

// Mirror of the server's _REJECT_REASONS keys.
const REJECT_OPTIONS: { code: string; label: string }[] = [
  { code: "duplicate", label: "уже есть в афише" },
  { code: "incomplete", label: "мало данных" },
  { code: "not_event", label: "не событие" },
  { code: "past", label: "уже прошло" },
  { code: "spam", label: "спам" },
  { code: "other", label: "другое" },
];

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function eventDate(iso: string | undefined): string {
  if (!iso) return "дата не указана";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit" });
}

function price(d: Record<string, any>): string {
  if (d.is_free) return "бесплатно";
  const lo = d.price_min, hi = d.price_max;
  if (lo != null && hi != null && hi !== lo) return `${Math.round(lo)}–${Math.round(hi)} ₽`;
  if (lo != null) return `от ${Math.round(lo)} ₽`;
  if (hi != null) return `до ${Math.round(hi)} ₽`;
  return "цена не указана";
}

function freshDays(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  return days <= 0 ? "сегодня" : days === 1 ? "вчера" : `${days} дн назад`;
}

const PROBE_LABEL: Record<string, string> = { ok: "жив", preview_off: "превью выкл", gone: "мёртв", error: "не проверен" };

export function Moderation() {
  const [status, setStatus] = useState("needs_review");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [reason, setReason] = useState<Record<string, string>>({});
  const [lightbox, setLightbox] = useState<string | null>(null);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setLightbox(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox]);

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    p.set("page", String(page + 1));
    return `/moderation/queue?${p.toString()}`;
  }, [status, page]);

  const { data, error, loading, reload } = useApi<any>(path, 20000);
  const items: Sub[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const pending = data?.pending ?? 0;
  const pageSize = data?.page_size ?? 50;
  const pages = Math.max(1, Math.ceil(total / pageSize));

  async function act(id: string, kind: "approve" | "reject") {
    setBusy(id);
    setMsg(null);
    try {
      const body = kind === "reject" ? { reject_code: reason[id] ?? "other" } : undefined;
      await apiPost(`/moderation/${id}/${kind}`, body);
      setMsg(kind === "approve" ? "Одобрено — событие уйдёт на карту." : "Отклонено.");
      reload();
    } catch (e) {
      setMsg(e instanceof ApiError ? `Ошибка: ${e.message}` : "Ошибка");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">модерация</h1>
          <div className="page__sub">
            заявки пользователей · <b>{pending}</b> ждут проверки
          </div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        {STATUS_TABS.map((t) => (
          <button
            key={t.key || "all"}
            className={"btn " + (status === t.key ? "" : "btn--ghost")}
            onClick={() => { setStatus(t.key); setPage(0); }}
          >
            {t.label}
          </button>
        ))}
        <span className="filter-count">{loading ? "…" : `${total}`}</span>
      </div>

      {msg && <div className="state">{msg}</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}
      {loading && !data && <div className="state">загрузка…</div>}

      {data && !items.length && <div className="state">пусто</div>}

      <div className="modlist">
        {items.map((s) => {
          const d = s.data || {};
          const c = s.checks || {};
          const isChannel = s.kind === "channel";
          const place = [d.venue, d.address].filter(Boolean).join(" · ");
          const open = s.status === "needs_review";
          return (
            <div className="modcard" key={s.submission_id}>
              <div className="modcard__body">
                {isChannel ? (
                  <>
                    <div className="modcard__title">
                      <a href={`https://t.me/s/${d.username_norm}`} target="_blank" rel="noopener noreferrer">
                        @{d.username_norm}
                      </a>{" "}
                      <span className="code" style={{ fontSize: 11, opacity: 0.7 }}>канал</span>
                    </div>
                    <div className="modcard__meta">
                      <span className="code">{PROBE_LABEL[c.probe] ?? "?"}</span>
                      {c.subscribers != null && <span>{c.subscribers} подп.</span>}
                      {c.newest && <span>пост {freshDays(c.newest)}</span>}
                      {c.reactivation && <span className="code">реактивация</span>}
                      {s.city_slug && <span className="code">{s.city_slug}</span>}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="modcard__title">{d.title || "без названия"}</div>
                    {d.image && (
                      <img
                        className="modcard__poster"
                        src={d.image}
                        alt=""
                        loading="lazy"
                        title="нажми, чтобы увеличить"
                        onClick={() => setLightbox(d.image)}
                      />
                    )}
                    <div className="modcard__meta">
                      <span>{eventDate(d.date_start)}</span>
                      {d.category && <span className="code">{d.category}</span>}
                      <span>{price(d)}</span>
                      {s.city_slug && <span className="code">{s.city_slug}</span>}
                    </div>
                    {place && <div className="modcard__place">{place}</div>}
                    {d.description && <div className="modcard__desc">{String(d.description).slice(0, 400)}</div>}
                    {d.url && <div className="modcard__url muted code">{d.url}</div>}
                  </>
                )}
                <div className="modcard__foot muted">
                  от {s.submitted_username ? "@" + s.submitted_username : s.submitted_by} · {when(s.created_at)}
                  {s.status !== "needs_review" && <> · <span className="code">{s.status}</span></>}
                  {s.reject_code && <> · причина: {s.reject_code}</>}
                </div>
              </div>
              {open && (
                <div className="modcard__actions">
                  <button
                    className="btn btn--solid"
                    disabled={busy === s.submission_id}
                    onClick={() => act(s.submission_id, "approve")}
                  >
                    {busy === s.submission_id ? "…" : "одобрить"}
                  </button>
                  <div className="modcard__reject">
                    <select
                      value={reason[s.submission_id] ?? "other"}
                      onChange={(e) => setReason((r) => ({ ...r, [s.submission_id]: e.target.value }))}
                    >
                      {REJECT_OPTIONS.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
                    </select>
                    <button
                      className="btn btn--ghost"
                      disabled={busy === s.submission_id}
                      onClick={() => act(s.submission_id, "reject")}
                    >
                      отклонить
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {data && pages > 1 && (
        <div className="pager">
          <button className="iconbtn" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← назад</button>
          <span className="filter-count" style={{ margin: 0 }}>стр {page + 1} из {pages}</span>
          <button className="iconbtn" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>вперёд →</button>
        </div>
      )}

      {lightbox && (
        <div className="modlightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="постер события" />
        </div>
      )}
    </div>
  );
}

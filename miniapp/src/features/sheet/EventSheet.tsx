import { useEffect, useState, type CSSProperties } from "react";

import { fetchEventDetail, type EventDetail, type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";

type Props = {
  selected: EventItem | null;
  onClose: () => void;
};

const dateOnly = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
const timeOnly = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const date = dateOnly.format(d);
  // Hide the time for all-day events (no point showing 00:00).
  if (d.getHours() === 0 && d.getMinutes() === 0) return date;
  return `${date}, ${timeOnly.format(d)}`;
}

// source_best_url comes from ingested/scraped data — only allow http(s) so a
// `javascript:` scheme cannot turn the link into an XSS sink.
function safeHttpUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const parsed = new URL(u);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function stripHtml(text: string): string {
  return text
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&[a-z]+;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function formatPrice(price: number | null | undefined): string {
  if (price == null) return "Цена не указана";
  if (price === 0) return "Бесплатно";
  return `от ${Math.round(price)} ₽`;
}

export function EventSheet({ selected, onClose }: Props) {
  const [detail, setDetail] = useState<EventDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    if (!selected) return;
    const ctrl = new AbortController();
    fetchEventDetail(selected.event_id, ctrl.signal)
      .then(setDetail)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [selected]);

  if (!selected) return null;

  const meta = categoryMeta(selected.category);
  const occ = detail?.occurrences?.[0];
  const kickerDate = (() => {
    const iso = occ?.date_start || selected.date_start;
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" : dateOnly.format(d);
  })();
  const lat = selected.lat ?? occ?.lat ?? null;
  const lon = selected.lon ?? occ?.lon ?? null;
  const address = occ?.address || null;
  const venue = selected.venue || occ?.venue || null;
  const image = detail?.primary_image_url || "";
  const description = stripHtml(detail?.canonical_description || "");
  const sourceUrl = safeHttpUrl(occ?.source_best_url);
  const routeUrl = lat != null && lon != null ? `https://yandex.ru/maps/?ll=${lon}%2C${lat}&z=16&pt=${lon},${lat}` : null;

  return (
    <div className="sheet" role="dialog" aria-label={selected.title}>
      <div className="sheet__sticky">
        <span className="sheet__grip" />
        <button type="button" className="sheet__close" aria-label="Закрыть" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className={`sheet__hero${image ? "" : " sheet__hero--plain"}`} style={{ "--c": meta.color } as CSSProperties}>
        {image ? <img src={image} alt="" loading="lazy" /> : <span className="sheet__hero-glyph">{meta.glyph}</span>}
        <span className="sheet__kicker kicker">
          {meta.label}
          {kickerDate ? ` · ${kickerDate}` : ""}
        </span>
        <span className="sheet__chip" style={{ "--c": meta.color } as CSSProperties}>
          <span>{meta.glyph}</span>
          {meta.label}
        </span>
      </div>

      <div className="sheet__body">
        <h2 className="sheet__title">{selected.title}</h2>

        <div className="sheet__meta">
          <div className="meta-row">
            <span className="meta-row__glyph">📅</span>
            <span>
              {formatDate(occ?.date_start || selected.date_start)}
              {occ?.date_end ? ` — ${formatDate(occ.date_end)}` : ""}
            </span>
          </div>
          {venue && (
            <div className="meta-row">
              <span className="meta-row__glyph">📍</span>
              <span>
                {venue}
                {address ? <span className="meta-row__dim"> · {address}</span> : null}
              </span>
            </div>
          )}
          <div className="meta-row">
            <span className="meta-row__glyph">💰</span>
            <span>{formatPrice(occ?.price_min ?? selected.price_min)}</span>
            {detail?.age_limit ? <span className="badge">{detail.age_limit}</span> : null}
          </div>
        </div>

        {description && <p className="sheet__desc">{description}</p>}

        <div className="sheet__actions">
          {sourceUrl && (
            <a className="btn btn--primary" href={sourceUrl} target="_blank" rel="noopener noreferrer">
              Подробнее
            </a>
          )}
          {routeUrl && (
            <a className="btn btn--ghost" href={routeUrl} target="_blank" rel="noopener noreferrer">
              Маршрут
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

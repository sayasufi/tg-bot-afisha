import { useEffect, useState } from "react";

import { fetchEventDetail, type EventDetail, type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { CategoryIcon } from "../../lib/icons";

type Props = {
  selected: EventItem | null;
  onClose: () => void;
};

const dateOnly = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
const timeOnly = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });

// Short museum "accession" codes per category, for the catalogue affect.
const CAT_CODE: Record<string, string> = {
  concert: "КОНЦ",
  theatre: "ТЕАТР",
  exhibition: "ВЫСТ",
  standup: "СТЕНД",
  festival: "ФЕСТ",
  lecture: "ЛЕКЦ",
  kids: "ДЕТИ",
  other: "ПРОЧ",
};

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

// Stable 4-digit "accession" sequence from the event id.
function accessionNo(id: string | number): string {
  const s = String(id);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return String(h % 10000).padStart(4, "0");
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
  const address = occ?.address || null;
  const venue = selected.venue || occ?.venue || null;
  const image = detail?.primary_image_url || "";
  const description = stripHtml(detail?.canonical_description || "");
  const sourceUrl = safeHttpUrl(occ?.source_best_url);
  const lat = selected.lat ?? occ?.lat ?? null;
  const lon = selected.lon ?? occ?.lon ?? null;
  const routeUrl = lat != null && lon != null ? `https://yandex.ru/maps/?ll=${lon}%2C${lat}&z=16&pt=${lon},${lat}` : null;
  const accession = `АФ · ${accessionNo(selected.event_id)} / ${CAT_CODE[selected.category] || CAT_CODE.other}`;
  const dates =
    formatDate(occ?.date_start || selected.date_start) + (occ?.date_end ? ` — ${formatDate(occ.date_end)}` : "");

  return (
    <div className="sheet" role="dialog" aria-label={selected.title}>
      <div className="sheet__sticky">
        <span className="sheet__grip" />
        <button type="button" className="sheet__close" aria-label="Закрыть" onClick={onClose}>
          ✕
        </button>
      </div>

      {/* mounted print */}
      <div className="sheet__frame">
        {image ? <img src={image} alt="" loading="lazy" /> : <CategoryIcon cat={selected.category} size={64} className="sheet__plate-glyph" />}
        <span className="sheet__tag">
          <CategoryIcon cat={selected.category} size={13} />
          {meta.label}
        </span>
      </div>

      <div className="sheet__body">
        <span className="kicker">{accession}</span>
        <h2 className="sheet__title">{selected.title}</h2>

        <div className="sheet__meta">
          <div className="wall-label">
            <span className="wall-label__cap">Когда</span>
            <span className="wall-label__val">{dates || "—"}</span>
          </div>
          {venue && (
            <div className="wall-label">
              <span className="wall-label__cap">Где</span>
              <span className="wall-label__val">
                {venue}
                {address ? <span className="dim"> · {address}</span> : null}
              </span>
            </div>
          )}
          <div className="wall-label">
            <span className="wall-label__cap">Цена</span>
            <span className="wall-label__val">
              {formatPrice(occ?.price_min ?? selected.price_min)}
              {detail?.age_limit ? <span className="badge">{detail.age_limit}</span> : null}
            </span>
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

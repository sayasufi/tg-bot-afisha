import { useEffect, useRef, useState } from "react";

import { fetchEventDetail, type EventDetail, type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhen } from "../../lib/datetime";
import { Highlight } from "../../lib/highlight";
import { CategoryIcon, IconClose, IconHeart, IconShare } from "../../lib/icons";
import { haptic, shareEvent } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";

type Props = {
  selected: EventItem | null;
  query?: string;
  isFav: boolean;
  onToggleFav: () => void;
  onClose: () => void;
};

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

export function EventSheet({ selected, query, isFav, onToggleFav, onClose }: Props) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    setDetail(null);
    if (!selected) return;
    const ctrl = new AbortController();
    fetchEventDetail(selected.event_id, ctrl.signal)
      .then(setDetail)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [selected]);

  // Parallax: the cover drifts up slower than the content as the sheet scrolls.
  useEffect(() => {
    const sheet = sheetRef.current;
    if (!sheet) return;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const y = sheet.scrollTop;
        if (imgRef.current) imgRef.current.style.transform = `translateY(${Math.min(y * 0.25, 24)}px)`;
      });
    };
    sheet.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      sheet.removeEventListener("scroll", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [selected]);

  if (!selected) return null;

  const meta = categoryMeta(selected.category);
  const occ = detail?.occurrences?.[0];
  const address = occ?.address || null;
  const venue = selected.venue || occ?.venue || null;
  const image = safeHttpUrl(detail?.primary_image_url) || "";
  const description = stripHtml(detail?.canonical_description || "");
  const sourceUrl = safeHttpUrl(occ?.source_best_url);
  const lat = selected.lat ?? occ?.lat ?? null;
  const lon = selected.lon ?? occ?.lon ?? null;
  const routeUrl = lat != null && lon != null ? `https://yandex.ru/maps/?ll=${lon}%2C${lat}&z=16&pt=${lon},${lat}` : null;
  const accession = `ОКР · ${accessionNo(selected.event_id)} / ${CAT_CODE[selected.category] || CAT_CODE.other}`;
  const dates = formatWhen(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end);

  const onShare = () => {
    haptic("light");
    shareEvent({ title: selected.title, text: [dates, venue].filter(Boolean).join(" · "), url: sourceUrl });
  };

  return (
    <div className="sheet" role="dialog" aria-label={selected.title} ref={sheetRef}>
      <div className="sheet__sticky">
        <span className="sheet__grip" />
        <button
          type="button"
          className={`sheet__icon sheet__icon--fav${isFav ? " sheet__icon--on" : ""}`}
          aria-label="В избранное"
          aria-pressed={isFav}
          onClick={() => {
            haptic("light");
            onToggleFav();
          }}
        >
          <IconHeart filled={isFav} size={18} />
        </button>
        <button type="button" className="sheet__icon sheet__icon--share" aria-label="Поделиться" onClick={onShare}>
          <IconShare size={18} />
        </button>
        <button type="button" className="sheet__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </div>

      {/* mounted print */}
      <div className="sheet__frame">
        {image ? (
          <img ref={imgRef} src={image} alt="" loading="lazy" decoding="async" />
        ) : detail ? (
          <CategoryIcon cat={selected.category} size={64} className="sheet__plate-glyph" />
        ) : (
          <span className="printing">
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
        )}
        <span className="sheet__tag">
          <CategoryIcon cat={selected.category} size={13} />
          {meta.label}
        </span>
      </div>

      <div className="sheet__body">
        <span className="kicker">{accession}</span>
        <h2 className="sheet__title">
          <Highlight text={selected.title} query={query} />
        </h2>

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
              <span className="swipe">{formatPrice(occ?.price_min ?? selected.price_min)}</span>
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

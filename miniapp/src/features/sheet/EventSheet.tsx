import { useEffect, useRef, useState } from "react";

import { fetchEventDetail, prepareShare, type EventDetail, type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatDateChip, formatWhen, goNowState, venueHoursToday, whenTimeNote } from "../../lib/datetime";
import { formatDistance, nearLabel, walkMinutes, type LatLon } from "../../lib/distance";
import { Highlight } from "../../lib/highlight";
import { CategoryIcon, IconClose, IconHeart, IconShare } from "../../lib/icons";
import { getWebApp, haptic, shareEvent } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";
import { SimilarEvents } from "./SimilarEvents";
import { accessionNo, CAT_CODE, formatPrice, stripHtml } from "./sheetFormat";

type MetroPing = { name: string; meters: number };

type Props = {
  selected: EventItem | null;
  query?: string;
  userPos?: LatLon | null;
  items: EventItem[];
  siblings?: EventItem[]; // the other events at this same point (cluster) — swipe to flip
  metro?: MetroPing | null;
  isFav: boolean;
  onToggleFav: () => void;
  onSelect: (i: EventItem) => void;
  onShowMap?: () => void;
  onClose: () => void;
};

export function EventSheet({ selected, query, userPos, items, siblings, metro, isFav, onToggleFav, onSelect, onShowMap, onClose }: Props) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Prev/next event AT THE SAME POINT — the cluster the sheet was opened from.
  const sibIndex = siblings && selected ? siblings.findIndex((s) => s.event_id === selected.event_id) : -1;
  const hasSiblings = !!siblings && siblings.length > 1 && sibIndex >= 0;
  const nav = (dir: number) => {
    if (!hasSiblings || !siblings) return;
    const next = sibIndex + dir;
    if (next < 0 || next >= siblings.length) return; // no wrap — stop at the ends
    haptic("light");
    onSelect(siblings[next]);
  };
  const navRef = useRef(nav);
  navRef.current = nav;
  const hasSiblingsRef = useRef(hasSiblings);
  hasSiblingsRef.current = hasSiblings;

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

  // Gestures: swipe DOWN (from the top) to dismiss; swipe LEFT/RIGHT to flip to the
  // prev/next event at the SAME point. The axis locks on the first movement so the
  // two never fight, vertical dismiss only engages at the top (never steals the inner
  // scroll), and a swipe that begins on the horizontal "similar" strip is left to
  // scroll it natively.
  useEffect(() => {
    const sheet = sheetRef.current;
    if (!sheet) return;
    let startX = 0;
    let startY = 0;
    let dx = 0;
    let dy = 0;
    let axis: "" | "v" | "h" | "skip" = "";
    let onStrip = false;
    const onStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      dx = dy = 0;
      axis = "";
      onStrip = e.target instanceof Element && !!e.target.closest(".simstrip");
      sheet.style.transition = "";
    };
    const onMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      dx = e.touches[0].clientX - startX;
      dy = e.touches[0].clientY - startY;
      if (!axis) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return; // too small to decide
        if (Math.abs(dx) > Math.abs(dy) * 1.3 && hasSiblingsRef.current && !onStrip) axis = "h";
        else if (dy > 0 && sheet.scrollTop <= 0) axis = "v";
        else {
          axis = "skip"; // let the inner content scroll
          return;
        }
      }
      if (axis === "h") {
        sheet.style.transform = `translateX(${dx * 0.35}px)`;
        e.preventDefault();
      } else if (axis === "v") {
        if (dy <= 0 || sheet.scrollTop > 0) {
          sheet.style.transform = "";
          return;
        }
        sheet.style.transform = `translateY(${Math.min(dy, 600)}px)`;
        e.preventDefault();
      }
    };
    const onEnd = () => {
      if (axis === "h") {
        sheet.style.transition = "transform 0.2s var(--ease-cut)";
        sheet.style.transform = "";
        if (dx > 56) navRef.current(-1); // swipe right → previous
        else if (dx < -56) navRef.current(1); // swipe left → next
        window.setTimeout(() => (sheet.style.transition = ""), 210);
      } else if (axis === "v") {
        const dismiss = dy > 100;
        sheet.style.transition = "transform 0.22s var(--ease-cut)";
        sheet.style.transform = dismiss ? "translateY(105%)" : "";
        if (dismiss) window.setTimeout(() => onCloseRef.current(), 190);
        window.setTimeout(() => {
          sheet.style.transition = "";
          if (!dismiss) sheet.style.transform = "";
        }, 240);
      }
      axis = "";
    };
    sheet.addEventListener("touchstart", onStart, { passive: true });
    sheet.addEventListener("touchmove", onMove, { passive: false });
    sheet.addEventListener("touchend", onEnd);
    sheet.addEventListener("touchcancel", onEnd);
    return () => {
      sheet.removeEventListener("touchstart", onStart);
      sheet.removeEventListener("touchmove", onMove);
      sheet.removeEventListener("touchend", onEnd);
      sheet.removeEventListener("touchcancel", onEnd);
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
  // Build a walking route straight to the venue: from the user's location when
  // we have it (rtt=pd = pedestrian), otherwise let Yandex use "my location".
  const routeUrl =
    lat != null && lon != null
      ? userPos
        ? `https://yandex.ru/maps/?rtext=${userPos[0]},${userPos[1]}~${lat},${lon}&rtt=pd&z=16`
        : `https://yandex.ru/maps/?rtext=~${lat},${lon}&rtt=pd&z=16`
      : null;
  const near = nearLabel(userPos, lat != null && lon != null ? [lat, lon] : null);
  // Public catalogue code "MSK-04PN" (unique, stable, URL-ready) + category tag.
  // Falls back to the legacy hashed number only if a cached item predates `code`.
  const code = selected.code || detail?.code || `ОКР·${accessionNo(selected.event_id)}`;
  const accession = `${code} · ${CAT_CODE[selected.category] || CAT_CODE.other}`;
  const dates = formatWhen(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end);
  // The soonest session drives the headline (`dates`); show up to 3 more upcoming
  // sessions as chips (4 dates total), then a compact "+N" for the rest, so a long
  // recurring run isn't hidden behind its first date but doesn't flood the card.
  const upcoming = detail?.occurrences ?? [];
  const moreDates = upcoming.slice(1, 4);
  const extraDates = Math.max(0, upcoming.length - 4);
  // For an all-day event, show the venue's REAL hours today ("сегодня 10:00–20:00")
  // when we have them; otherwise an honest "время уточняйте". Never a misleading
  // "в часы работы" or a 24/7 "круглосуточно" (that's a matched-territory artefact —
  // venueHoursToday returns null for it).
  const baseNote = whenTimeNote(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end);
  const timeNote = baseNote ? venueHoursToday(occ?.venue_hours) ?? baseNote : "";
  // "Можно пойти сейчас" badge for the headline session — the soonest you can
  // still get to (occurrences are future-first): timed within 3 h, or open now.
  const go = goNowState(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end, occ?.venue_hours);

  const onShare = async () => {
    haptic("light");
    const wa = getWebApp();
    // Preferred: send a real photo message (Bot API 8.0 shareMessage) — the card
    // appears as an image in the chat, not a link with a preview.
    if (wa?.initData && typeof wa.shareMessage === "function") {
      const prepared = await prepareShare(selected.event_id);
      if (prepared.ok && prepared.id) {
        wa.shareMessage(prepared.id);
        return;
      }
    }
    // Fallback (older clients / no photo): share the branded OG page link.
    const shareUrl = `${window.location.origin}/v1/share/${selected.event_id}`;
    shareEvent({ title: selected.title, text: [dates, venue].filter(Boolean).join(" · "), url: shareUrl });
  };

  return (
    <>
      <div className="sheet-veil" onClick={onClose} />
      <div className="sheet" role="dialog" aria-label={selected.title} ref={sheetRef}>
        <div className="sheet__sticky">
          <span className="sheet__grip" />
          {hasSiblings && siblings && (
            <div className="sheet__sibs" aria-label="События в этой точке">
              <button type="button" className="sheet__sib-nav" aria-label="Предыдущее" disabled={sibIndex <= 0} onClick={() => nav(-1)}>
                ‹
              </button>
              <span className="sheet__sib-count">
                {sibIndex + 1} / {siblings.length}
              </span>
              <button type="button" className="sheet__sib-nav" aria-label="Следующее" disabled={sibIndex >= siblings.length - 1} onClick={() => nav(1)}>
                ›
              </button>
            </div>
          )}
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
          <img
            ref={imgRef}
            src={image}
            alt=""
            loading="lazy"
            decoding="async"
            className="sheet__cover-img"
            onLoad={(e) => e.currentTarget.classList.add("is-developed")}
          />
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
            {go.eligible && <span className="sheet__gonow">{go.kind === "soon" ? go.label : "идёт сейчас"}</span>}
            <span className="wall-label__val">
              {dates || "—"}
              {timeNote && <span className="dim"> · {timeNote}</span>}
            </span>
            {moreDates.length > 0 && (
              <div className="sheet__dates" aria-label="Ближайшие даты">
                {moreDates.map((o) => (
                  <span className="sheet__date-chip" key={o.occurrence_id}>
                    {formatDateChip(o.date_start)}
                  </span>
                ))}
                {extraDates > 0 && <span className="sheet__date-more">+{extraDates}</span>}
              </div>
            )}
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
          {metro && metro.meters <= 2500 && (
            <div className="wall-label">
              <span className="wall-label__cap">Метро</span>
              <span className="wall-label__val">
                <span className="sheet__metro">м. {metro.name}</span>
                <span className="dim"> · {formatDistance(metro.meters)} · {walkMinutes(metro.meters)} мин</span>
              </span>
            </div>
          )}
          {near && (
            <div className="wall-label">
              <span className="wall-label__cap">От тебя</span>
              <span className="wall-label__val">
                <span className="sheet__near">{near}</span>
              </span>
            </div>
          )}
          <div className="wall-label">
            <span className="wall-label__cap">Цена</span>
            <span className="wall-label__val">
              <span className="swipe">{formatPrice(occ?.price_min ?? selected.price_min, occ?.price_max)}</span>
              {detail?.age_limit ? <span className="badge">{detail.age_limit}</span> : null}
            </span>
          </div>
        </div>

        {description && <p className="sheet__desc">{description}</p>}

        {(sourceUrl || routeUrl || (onShowMap && lat != null && lon != null)) && (
          <div className="sheet__actions">
            {sourceUrl && (
              <a className="btn btn--primary" href={sourceUrl} target="_blank" rel="noopener noreferrer">
                Подробнее
              </a>
            )}
            {onShowMap && lat != null && lon != null && (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  haptic("light");
                  onShowMap();
                }}
              >
                На карте
              </button>
            )}
            {routeUrl && (
              <a className="btn btn--ghost" href={routeUrl} target="_blank" rel="noopener noreferrer">
                Маршрут
              </a>
            )}
          </div>
        )}

        <SimilarEvents selected={selected} items={items} userPos={userPos} onSelect={onSelect} />
        </div>
      </div>
    </>
  );
}

import { useEffect, useRef, useState } from "react";

import { fetchEventDetail, prepareShare, type EventDetail, type EventItem } from "../../api/client";
import { logIntent } from "../../api/intent";
import { categoryMeta } from "../../lib/categories";
import { formatDateChip, formatWhen, goNowState, venueHoursToday, venueOpenNow, whenTimeNote } from "../../lib/datetime";
import { formatDistance, nearLabel, walkMinutes, type LatLon } from "../../lib/distance";
import { Highlight } from "../../lib/highlight";
import { CategoryIcon, IconBell, IconClose, IconHeart, IconPin, IconShare } from "../../lib/icons";
import { pushSetting } from "../../lib/settings";
import { getWebApp, haptic, shareEvent } from "../../lib/telegram";
import { showToast } from "../../lib/toast";
import { safeHttpUrl } from "../../lib/url";
import { SimilarEvents } from "./SimilarEvents";
import { accessionNo, formatPrice, stripHtml } from "./sheetFormat";

// Trust line helpers: the source host ("по данным afisha.ru") and a human freshness date.
function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}
const ACTUAL_FMT = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
function formatActualDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : ACTUAL_FMT.format(new Date(t));
}

function pluralDates(n: number): string {
  const d = n % 10;
  const dd = n % 100;
  if (d === 1 && dd !== 11) return "дата";
  if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return "даты";
  return "дат";
}

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
  hasReminder: boolean;
  onToggleReminder: () => void;
  onSelect: (i: EventItem) => void;
  onShowMap?: () => void;
  onOpenVenue?: (venueId: number) => void;
  onClose: () => void;
};

export function EventSheet({ selected, query, userPos, items, siblings, metro, isFav, onToggleFav, hasReminder, onToggleReminder, onSelect, onShowMap, onOpenVenue, onClose }: Props) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [descOpen, setDescOpen] = useState(false);
  const [datesOpen, setDatesOpen] = useState(false);
  const [swipeHint, setSwipeHint] = useState(false);
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
    setDescOpen(false);
    setDatesOpen(false);
    if (!selected) return;
    const ctrl = new AbortController();
    fetchEventDetail(selected.event_id, ctrl.signal)
      .then(setDetail)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [selected]);

  // A cached cover can already be `complete` before onLoad binds (so it would stay
  // permanently blurred), and a broken image must not stay blurred either — develop
  // on mount if loaded, and on error.
  useEffect(() => {
    const img = imgRef.current;
    if (img && img.complete) img.classList.add("is-developed");
  });

  // One-time hint that you can swipe between events at the same point (the ‹ › arrows
  // also work). Shown once ever, only when the opened pin has siblings.
  useEffect(() => {
    if (!selected || !hasSiblings) return;
    try {
      if (localStorage.getItem("okrest_swipe_seen") === "1") return;
      localStorage.setItem("okrest_swipe_seen", "1");
    } catch {
      return;
    }
    pushSetting("swipe_seen", true); // remember on the account, not just this device
    setSwipeHint(true);
    const t = setTimeout(() => setSwipeHint(false), 3800);
    return () => clearTimeout(t);
  }, [selected, hasSiblings]);

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
  const venueId = occ?.venue_id ?? selected.venue_id ?? null; // map item carries it pre-detail
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
  const dates = formatWhen(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end);
  // The soonest session drives the headline (`dates`); show up to 3 more sessions as
  // chips, then a compact "+N" for the rest. Chips list only sessions that HAVEN'T
  // started yet — an ongoing run's past start date (e.g. an exhibition that opened
  // 16 июн and runs through 21 июн) isn't a meaningful "next date"; that the event is
  // happening now is already carried by the headline + "идёт сейчас" badge.
  const nowMs = Date.now();
  const futureMore = (detail?.occurrences ?? [])
    .slice(1)
    .filter((o) => o.date_start && Date.parse(o.date_start) > nowMs);
  const moreDates = futureMore.slice(0, 3);
  const extraDates = Math.max(0, futureMore.length - 3);
  // For an all-day event, show the venue's REAL hours today ("сегодня 10:00–20:00")
  // when we have them; otherwise an honest "время уточняйте". Never a misleading
  // "в часы работы" or a 24/7 "круглосуточно" (that's a matched-territory artefact —
  // venueHoursToday returns null for it).
  const baseNote = whenTimeNote(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end);
  const timeNote = baseNote ? venueHoursToday(occ?.venue_hours) ?? baseNote : "";
  // "Можно пойти сейчас" badge for the headline session — the soonest you can
  // still get to (occurrences are future-first): timed within 3 h, or open now.
  // The detail occurrence carries full hours → derive open-now from them; before the
  // detail loads, fall back to the map item's server-computed open_now.
  const openNow = venueOpenNow(occ?.venue_hours) ?? selected.open_now ?? null;
  const go = goNowState(occ?.date_start ?? selected.date_start, occ?.date_end ?? selected.date_end, openNow);

  // The source link is the primary "act on it" click — plain "Подробнее".
  const ticketLabel = "Подробнее";

  // Trust line: where the data is from + when it was last refreshed + a way to flag it wrong.
  const sourceHost = sourceUrl ? hostOf(sourceUrl) : null;
  const updatedLabel = formatActualDate(detail?.updated_at);
  const onReport = () => {
    haptic("light");
    const link = `https://t.me/okrestmap_bot?start=report_${selected.event_id}`;
    const wa = getWebApp();
    if (wa?.openTelegramLink) wa.openTelegramLink(link);
    else window.open(link, "_blank");
  };

  const onShare = async () => {
    haptic("light");
    logIntent("share", selected.event_id);
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
          {swipeHint && hasSiblings && <div className="sheet__swipehint" aria-hidden="true">‹ листайте между событиями ›</div>}
      </div>

      {/* One exhibit card — poster + title + grid + actions all inside a single ink
          frame with a big acid registration offset. Trust + similar sit below it. */}
      <div className="sheet__card">
      {/* afisha — accession code on the frame, category tag bottom-left, live badge bottom-right. */}
      <div className={`sheet__frame${image ? " sheet__frame--photo" : ""}`}>
        {image ? (
          <img
            ref={imgRef}
            src={image}
            alt=""
            loading="lazy"
            decoding="async"
            className="sheet__cover-img"
            onLoad={(e) => e.currentTarget.classList.add("is-developed")}
            onError={(e) => e.currentTarget.classList.add("is-developed")}
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
        {image ? <span className="sheet__scrim" aria-hidden="true" /> : null}
        <span className="sheet__code">{code}</span>
        <span className="sheet__tag">
          <CategoryIcon cat={selected.category} size={13} />
          {meta.label}
        </span>
        {go.eligible && (
          <span className="sheet__live">
            <i className="sheet__live-dot" aria-hidden="true" />
            {go.kind === "soon" ? go.label : "идёт сейчас"}
          </span>
        )}
        {/* Segmented action toolbar, docked flush to the poster's top-right corner so its top
            edge meets the start of the photo: favourite / reminder / share / close. */}
        <div className="sheet__pacts">
          <button
            type="button"
            className={`sheet__picon${isFav ? " sheet__picon--on" : ""}`}
            aria-label="В избранное"
            aria-pressed={isFav}
            onClick={() => {
              haptic("light");
              showToast(isFav ? "Убрано из избранного" : "Добавлено в избранное", {
                icon: "heart",
                tone: isFav ? "muted" : "good",
              });
              onToggleFav();
            }}
          >
            <IconHeart filled={isFav} size={16} />
          </button>
          <button
            type="button"
            className={`sheet__picon${hasReminder ? " sheet__picon--on" : ""}`}
            aria-label={hasReminder ? "Напоминание включено" : "Напомнить о начале"}
            aria-pressed={hasReminder}
            onClick={() => {
              haptic("light");
              if (!hasReminder) logIntent("reminder", selected.event_id);
              showToast(hasReminder ? "Напоминание выключено" : "Напомним перед началом", {
                icon: "bell",
                tone: hasReminder ? "muted" : "good",
              });
              onToggleReminder();
            }}
          >
            <IconBell filled={hasReminder} size={16} />
          </button>
          <button type="button" className="sheet__picon" aria-label="Поделиться" onClick={onShare}>
            <IconShare size={16} />
          </button>
          <button type="button" className="sheet__picon sheet__picon--close" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={16} />
          </button>
        </div>
      </div>

      <div className="sheet__head">
        <h2 className="sheet__title">
          <Highlight text={selected.title} query={query} />
        </h2>
      </div>

      {/* Exhibit grid — each datum its own hairline cell, museum-catalogue style. */}
        <div className="xgrid">
          <div className="xcell">
            <span className="xcell__cap">Когда</span>
            <span className="xcell__val">{dates || "—"}</span>
            {timeNote && <span className="xcell__sub">{timeNote}</span>}
            {futureMore.length > 0 &&
              (datesOpen ? (
                <div className="sheet__dates" aria-label="Другие даты">
                  {moreDates.map((o) => (
                    <span className="sheet__date-chip" key={o.occurrence_id}>
                      {formatDateChip(o.date_start)}
                    </span>
                  ))}
                  {extraDates > 0 && <span className="sheet__date-more">+{extraDates}</span>}
                </div>
              ) : (
                <button type="button" className="xcell__more" onClick={() => setDatesOpen(true)}>
                  +{futureMore.length} {pluralDates(futureMore.length)}
                </button>
              ))}
          </div>
          <div className="xcell">
            <span className="xcell__cap">Цена</span>
            <span className="xcell__val xcell__price">
              {formatPrice(occ?.price_min ?? selected.price_min, occ?.price_max)}
            </span>
          </div>
          {venue &&
            (venueId != null && onOpenVenue ? (
              <button
                type="button"
                className="xcell xcell--wide xcell--place"
                onClick={() => {
                  haptic("light");
                  onOpenVenue(venueId);
                }}
              >
                <span className="xcell__cap">Где</span>
                <span className="xcell__place">
                  <IconPin size={15} className="xcell__pin" />
                  <span className="xcell__placetext">
                    <span className="xcell__val">{venue}</span>
                    {address ? <span className="xcell__sub">{address}</span> : null}
                  </span>
                  <span className="xcell__go" aria-hidden="true" />
                </span>
              </button>
            ) : (
              <div className="xcell xcell--wide">
                <span className="xcell__cap">Где</span>
                <span className="xcell__val">{venue}</span>
                {address ? <span className="xcell__sub">{address}</span> : null}
              </div>
            ))}
          {metro && metro.meters <= 2500 && near ? (
            <>
              <div className="xcell">
                <span className="xcell__cap">Метро</span>
                <span className="xcell__val">м. {metro.name}</span>
                <span className="xcell__sub">
                  {formatDistance(metro.meters)} · {walkMinutes(metro.meters)} мин
                </span>
              </div>
              <div className="xcell">
                <span className="xcell__cap">От тебя</span>
                <span className="xcell__val">{near}</span>
              </div>
            </>
          ) : metro && metro.meters <= 2500 ? (
            <div className="xcell xcell--wide">
              <span className="xcell__cap">Метро</span>
              <span className="xcell__val">
                м. {metro.name} · {formatDistance(metro.meters)} · {walkMinutes(metro.meters)} мин
              </span>
            </div>
          ) : near ? (
            <div className="xcell xcell--wide">
              <span className="xcell__cap">От тебя</span>
              <span className="xcell__val">{near}</span>
            </div>
          ) : null}
        </div>

        {description && (
          <div className={`sheet__desc-wrap${descOpen ? " is-open" : ""}`}>
            <p className="sheet__desc">{description}</p>
            {!descOpen && description.length > 220 && (
              <button type="button" className="sheet__desc-more" onClick={() => setDescOpen(true)}>
                читать дальше
              </button>
            )}
          </div>
        )}

        {(sourceUrl || routeUrl || (onShowMap && lat != null && lon != null)) && (
          <div className="sheet__actions">
            {sourceUrl && (
              <a
                className="btn btn--primary"
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => logIntent("click", selected.event_id)}
              >
                {ticketLabel}
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
              <a
                className="btn btn--ghost"
                href={routeUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => logIntent("route", selected.event_id)}
              >
                Маршрут
              </a>
            )}
          </div>
        )}

      </div>

      <div className="sheet__after">
        {(sourceHost || updatedLabel) && (
          <p className="sheet__trust">
            {sourceHost && <span>по данным {sourceHost}</span>}
            {sourceHost && updatedLabel && <span aria-hidden="true"> · </span>}
            {updatedLabel && <span>актуально на {updatedLabel}</span>}
            <span aria-hidden="true"> · </span>
            <button type="button" className="sheet__trust-report" onClick={onReport}>
              сообщить о неточности
            </button>
          </p>
        )}

        <SimilarEvents selected={selected} items={items} userPos={userPos} onSelect={onSelect} />
        </div>
      </div>
    </>
  );
}

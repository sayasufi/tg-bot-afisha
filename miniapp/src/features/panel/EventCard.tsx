import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort, goNowState } from "../../lib/datetime";
import { distanceLabel, formatDistance, type LatLon } from "../../lib/distance";
import { CategoryIcon } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";

export type CardItem = EventItem & { distance_m?: number | null };

function priceLabel(p: number | null | undefined): { text: string; free: boolean } | null {
  if (p == null) return null;
  if (p <= 0) return { text: "бесплатно", free: true };
  return { text: `от ${Math.round(p).toLocaleString("ru-RU")} ₽`, free: false };
}

// One event as a full-bleed poster card — the same editorial language as the list/favorites
// rows (photo darkened, type set OVER it), sized for the horizontal rec rails: category +
// code top, live badge / title / meta · price at the bottom.
export function EventCard({ item, index = 0, userPos, onSelect }: { item: CardItem; index?: number; userPos?: LatLon | null; onSelect: (i: EventItem) => void }) {
  const meta = categoryMeta(item.category);
  const go = goNowState(item.date_start, item.date_end, item.open_now);
  const img = safeHttpUrl(item.primary_image_url);
  const dist =
    item.distance_m != null
      ? formatDistance(item.distance_m)
      : item.lat != null && item.lon != null
        ? distanceLabel(userPos, [item.lat, item.lon])
        : null;
  const when = formatWhenShort(item.date_start, item.date_end);
  const price = priceLabel(item.price_min);
  // On the narrow rail card show just WHEN — the venue truncates to a useless stub here
  // ("Но…"), and distance already sits top-right. (The full-width list rows keep the venue.)
  const metaLine = when;
  return (
    <button
      type="button"
      className={`rcard${img ? "" : " rcard--noimg"}`}
      style={{ "--i": Math.min(index, 8) } as CSSProperties}
      aria-label={`${item.title}. ${meta.label}. ${when}${dist ? `. ${dist}` : ""}${price ? `. ${price.text}` : ""}`}
      onClick={() => onSelect(item)}
    >
      {img ? (
        <img className="rcard__img" src={img} alt="" loading="lazy" decoding="async" />
      ) : (
        <span className="rcard__glyph" aria-hidden="true">
          <CategoryIcon cat={item.category} size={34} />
        </span>
      )}
      {img && <span className="poster-grain" aria-hidden="true" />}
      <span className="rcard__top">
        <span className="rcard__tag">
          <CategoryIcon cat={item.category} size={13} className="rcard__cat" />
          {item.code && <span className="rcard__code">{item.code}</span>}
        </span>
        {dist && <span className="rcard__dist">{dist}</span>}
      </span>
      <span className="rcard__btm">
        {go.eligible && <span className="rcard__live">{go.kind === "soon" ? go.label : "идёт сейчас"}</span>}
        <span className="rcard__title">{item.title}</span>
        <span className="rcard__foot">
          {metaLine && <span className="rcard__meta">{metaLine}</span>}
          {price && <span className={`rcard__price${price.free ? " rcard__price--free" : ""}`}>{price.text}</span>}
        </span>
      </span>
    </button>
  );
}

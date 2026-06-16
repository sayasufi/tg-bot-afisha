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

// One event as a photo card — used by the recommendation rails and the favourites
// grid. A muted cover with a category-colour rail, a calm live indicator, a price
// tag, then title + when/distance.
export function EventCard({ item, userPos, onSelect }: { item: CardItem; userPos?: LatLon | null; onSelect: (i: EventItem) => void }) {
  const meta = categoryMeta(item.category);
  const go = goNowState(item.date_start, item.date_end, item.venue_hours);
  const img = safeHttpUrl(item.primary_image_url);
  const dist =
    item.distance_m != null
      ? formatDistance(item.distance_m)
      : item.lat != null && item.lon != null
        ? distanceLabel(userPos, [item.lat, item.lon])
        : null;
  const when = formatWhenShort(item.date_start, item.date_end);
  const price = priceLabel(item.price_min);
  return (
    <button
      type="button"
      className="rcard"
      style={{ "--cat": meta.color } as CSSProperties}
      aria-label={`${item.title}. ${meta.label}. ${when}${dist ? `. ${dist}` : ""}${price ? `. ${price.text}` : ""}`}
      onClick={() => onSelect(item)}
    >
      <span className="rcard__img">
        {img ? (
          <img src={img} alt={item.title} loading="lazy" decoding="async" />
        ) : (
          <span className="rcard__ph">
            <CategoryIcon cat={item.category} size={30} />
          </span>
        )}
        <span className="rcard__scrim" aria-hidden="true" />
        {go.eligible && (
          <span className="rcard__live">
            <i className="rcard__livedot" aria-hidden="true" />
            {go.kind === "soon" ? go.label : "идёт сейчас"}
          </span>
        )}
        {price && <span className={`rcard__price${price.free ? " rcard__price--free" : ""}`}>{price.text}</span>}
      </span>
      <span className="rcard__title">{item.title}</span>
      <span className="rcard__meta">
        {when}
        {dist ? ` · ${dist}` : ""}
      </span>
    </button>
  );
}

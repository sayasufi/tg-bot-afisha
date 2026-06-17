import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort, goNowState } from "../../lib/datetime";
import { distanceLabel, type LatLon } from "../../lib/distance";
import { CategoryIcon } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";

function priceLabel(p: number | null | undefined): string | null {
  if (p == null) return null;
  if (p <= 0) return "бесплатно";
  return `от ${Math.round(p).toLocaleString("ru-RU")} ₽`;
}

// A list-view row: photo thumbnail + title + when/venue + price/distance. Heavier than
// EventRow (which is glyph-only) because the list is meant for browsing with images.
export function EventListRow({
  item,
  index,
  userPos,
  onSelect,
}: {
  item: EventItem;
  index: number;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
}) {
  const img = safeHttpUrl(item.primary_image_url);
  const dist = item.lat != null && item.lon != null ? distanceLabel(userPos, [item.lat, item.lon]) : null;
  const go = goNowState(item.date_start, item.date_end, item.open_now);
  const when = formatWhenShort(item.date_start, item.date_end);
  const price = priceLabel(item.price_min);

  return (
    <button type="button" className="lrow" style={{ "--i": index } as CSSProperties} onClick={() => onSelect(item)}>
      <span className="lrow__thumb">
        {img ? (
          <img src={img} alt="" loading="lazy" decoding="async" />
        ) : (
          <CategoryIcon cat={item.category} size={30} />
        )}
        {go.eligible && <i className="lrow__spark" aria-hidden="true" />}
      </span>
      <span className="lrow__body">
        {item.code && <span className="lrow__code">{item.code}</span>}
        <span className="lrow__title">{item.title}</span>
        <span className="lrow__meta">
          {go.eligible && <span className="lrow__live">{go.kind === "soon" ? go.label : "идёт сейчас"}</span>}
          {go.eligible ? " · " : ""}
          {when}
          {item.venue ? ` · ${item.venue}` : ""}
        </span>
      </span>
      <span className="lrow__side">
        {dist && <span className="lrow__dist">{dist}</span>}
        {price && <span className={`lrow__price${price === "бесплатно" ? " lrow__price--free" : ""}`}>{price}</span>}
      </span>
    </button>
  );
}

import { memo, type CSSProperties } from "react";

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

// A list-view card: the event photo fills the whole tile, darkened, with the title and
// data set over it — a full-bleed "poster" catalogue entry (no padding, edge to edge).
// memo'd: props are primitives + a stable onSelect, so appended pages don't re-render
// already-mounted rows.
function EventListRowImpl({
  item,
  index,
  userPos,
  now,
  onSelect,
}: {
  item: EventItem;
  index: number;
  userPos?: LatLon | null;
  now?: number; // shared minute-tick, so the list's "идёт сейчас"/countdown matches the map
  onSelect: (i: EventItem) => void;
}) {
  const img = safeHttpUrl(item.primary_image_url);
  const dist = item.lat != null && item.lon != null ? distanceLabel(userPos, [item.lat, item.lon]) : null;
  const nowDate = now != null ? new Date(now) : undefined;
  const go = goNowState(item.date_start, item.date_end, item.open_now, nowDate);
  const when = formatWhenShort(item.date_start, item.date_end, nowDate);
  const price = priceLabel(item.price_min);
  const meta = [when, item.venue].filter(Boolean).join(" · ");

  return (
    <button
      type="button"
      className={`lrow${img ? "" : " lrow--noimg"}`}
      style={{ "--i": Math.min(index, 8) } as CSSProperties}
      onClick={() => onSelect(item)}
    >
      {img ? (
        <img className="lrow__img" src={img} alt="" loading="lazy" decoding="async" />
      ) : (
        <span className="lrow__glyph">
          <CategoryIcon cat={item.category} size={44} />
        </span>
      )}
      <span className="lrow__top">
        {item.code && <span className="lrow__code">{item.code}</span>}
        {dist && <span className="lrow__dist">{dist}</span>}
      </span>
      <span className="lrow__btm">
        {go.eligible && <span className="lrow__live">{go.kind === "soon" ? go.label : "идёт сейчас"}</span>}
        <span className="lrow__title">{item.title}</span>
        <span className="lrow__foot">
          {meta && <span className="lrow__meta">{meta}</span>}
          {price && <span className={`lrow__price${price === "бесплатно" ? " lrow__price--free" : ""}`}>{price}</span>}
        </span>
      </span>
    </button>
  );
}

export const EventListRow = memo(EventListRowImpl);

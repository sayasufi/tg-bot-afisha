import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort } from "../../lib/datetime";
import { distanceLabel, type LatLon } from "../../lib/distance";
import { Highlight } from "../../lib/highlight";
import { CategoryIcon } from "../../lib/icons";

export function EventRow({
  item,
  index,
  query,
  userPos,
  onSelect,
}: {
  item: EventItem;
  index: number;
  query?: string;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
}) {
  const dist =
    item.lat != null && item.lon != null ? distanceLabel(userPos, [item.lat, item.lon]) : null;

  return (
    <button
      type="button"
      className="erow"
      style={{ "--i": index } as CSSProperties}
      onClick={() => onSelect(item)}
    >
      <span className="erow__mark">
        <CategoryIcon cat={item.category} size={22} />
      </span>
      <span className="erow__body">
        <span className="erow__title">
          <Highlight text={item.title} query={query} />
        </span>
        <span className="erow__meta">
          {formatWhenShort(item.date_start, item.date_end)}
          {item.venue ? ` · ${item.venue}` : ""}
        </span>
      </span>
      {dist && <span className="erow__dist">{dist}</span>}
    </button>
  );
}

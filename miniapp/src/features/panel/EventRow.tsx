import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort, goNowState } from "../../lib/datetime";
import { distanceLabel, type LatLon } from "../../lib/distance";
import { Highlight } from "../../lib/highlight";
import { CategoryIcon } from "../../lib/icons";
import { GoingBadge } from "./GoingBadge";

export function EventRow({
  item,
  index,
  query,
  userPos,
  now,
  active,
  optionId,
  onSelect,
}: {
  item: EventItem;
  index: number;
  query?: string;
  userPos?: LatLon | null;
  now?: number;
  active?: boolean; // keyboard-highlighted (search combobox)
  optionId?: string; // present → render as a listbox option
  onSelect: (i: EventItem) => void;
}) {
  const dist =
    item.lat != null && item.lon != null ? distanceLabel(userPos, [item.lat, item.lon]) : null;
  // The "можно пойти сейчас" spark — same predicate that reddens the map pin, off the
  // SAME shared minute-tick as goNowIds, so the list never disagrees with the map.
  const go = goNowState(item.date_start, item.date_end, item.open_now, now ? new Date(now) : new Date());

  return (
    <button
      type="button"
      className={`erow${go.eligible ? " erow--live" : ""}${active ? " erow--active" : ""}`}
      style={{ "--i": index } as CSSProperties}
      id={optionId}
      role={optionId ? "option" : undefined}
      aria-selected={optionId ? !!active : undefined}
      onClick={() => onSelect(item)}
    >
      <span className="erow__mark">
        <CategoryIcon cat={item.category} size={22} />
        {go.eligible && <i className="erow__spark" aria-hidden="true" />}
      </span>
      <span className="erow__body">
        <span className="erow__title">
          <Highlight text={item.title} query={query} />
          <GoingBadge eventId={item.event_id} className="erow__going" />
        </span>
        <span className="erow__meta">
          {query && item.code && <span className="erow__code">{item.code}</span>}
          {query && item.code ? " · " : ""}
          {go.eligible && <span className="erow__live">{go.kind === "soon" ? go.label : "идёт сейчас"}</span>}
          {go.eligible ? " · " : ""}
          {formatWhenShort(item.date_start, item.date_end)}
          {item.venue ? ` · ${item.venue}` : ""}
        </span>
      </span>
      {dist && <span className="erow__dist">{dist}</span>}
    </button>
  );
}

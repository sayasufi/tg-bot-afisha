import { useMemo } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort, mskEndOfTodayMs } from "../../lib/datetime";
import { distanceLabel, distanceMeters, type LatLon } from "../../lib/distance";
import { CategoryIcon } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";

// "Рядом ещё" — the closest events that are on TODAY (ongoing now or starting
// today), as a compact swipeable card strip. Future events are excluded: the
// point is "what else can I go to right now, nearby".
export function SimilarEvents({
  selected,
  items,
  userPos,
  onSelect,
}: {
  selected: EventItem;
  items: EventItem[];
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
}) {
  // Memoised: the sheet re-renders on every goNow tick and UI toggle; without this the distance
  // sort over ALL visible events re-ran each time. Keyed on the event + the item set only.
  const near = useMemo(() => {
    if (selected.lat == null || selected.lon == null) return [];
    const here: LatLon = [selected.lat, selected.lon];
    const endOfTodayMs = mskEndOfTodayMs(); // end of *Moscow* today, not the viewer's
    const onToday = (iso: string | null) => {
      if (!iso) return false;
      const t = Date.parse(iso);
      // Items are already filtered server-side to "not yet ended", so a start at
      // or before end-of-today means it is ongoing or starts today.
      return !Number.isNaN(t) && t <= endOfTodayMs;
    };
    return items
      .filter((it) => it.event_id !== selected.event_id && it.lat != null && it.lon != null && onToday(it.date_start))
      .map((it) => ({ it, d: distanceMeters(here, [it.lat as number, it.lon as number]) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 8);
  }, [selected, items]);
  if (near.length === 0) return null;

  return (
    <div className="sheet__similar">
      <div className="sheet__similar-head">
        Рядом сегодня
        <span className="recs__n">{near.length}</span>
      </div>
      <div className="simstrip">
        {near.map(({ it }) => {
          const dist = it.lat != null && it.lon != null ? distanceLabel(userPos, [it.lat, it.lon]) : null;
          const image = safeHttpUrl(it.primary_image_url);
          return (
            <button key={it.event_id} type="button" className="simcard" onClick={() => onSelect(it)}>
              <span className="simcard__cover">
                {image ? (
                  <img src={image} alt="" loading="lazy" decoding="async" />
                ) : (
                  <CategoryIcon cat={it.category} size={30} />
                )}
              </span>
              <span className="simcard__body">
                <span className="simcard__title">{it.title}</span>
                <span className="simcard__meta">
                  <span className="simcard__when">{formatWhenShort(it.date_start, it.date_end)}</span>
                  {dist && <span className="simcard__dist">{dist}</span>}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

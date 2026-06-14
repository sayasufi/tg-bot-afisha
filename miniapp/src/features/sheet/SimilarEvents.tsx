import type { EventItem } from "../../api/client";
import { formatWhenShort } from "../../lib/datetime";
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
  if (selected.lat == null || selected.lon == null) return null;
  const here: LatLon = [selected.lat, selected.lon];

  const now = new Date();
  const endOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
  const onToday = (iso: string | null) => {
    if (!iso) return false;
    const d = new Date(iso);
    // Items are already filtered server-side to "not yet ended", so a start at
    // or before end-of-today means it is ongoing or starts today.
    return !Number.isNaN(d.getTime()) && d <= endOfToday;
  };

  const near = items
    .filter((it) => it.event_id !== selected.event_id && it.lat != null && it.lon != null && onToday(it.date_start))
    .map((it) => ({ it, d: distanceMeters(here, [it.lat as number, it.lon as number]) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, 8);
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

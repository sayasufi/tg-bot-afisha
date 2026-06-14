import type { EventItem } from "../../api/client";
import { formatWhenShort } from "../../lib/datetime";
import { distanceLabel, distanceMeters, type LatLon } from "../../lib/distance";
import { CategoryIcon } from "../../lib/icons";

// "Рядом ещё" — the closest other events, as a compact swipeable card strip
// (gallery plates with vinyl-cut category icons), so it reads as "related items"
// rather than a second list dumped into the sheet.
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
  const near = items
    .filter((it) => it.event_id !== selected.event_id && it.lat != null && it.lon != null)
    .map((it) => ({ it, d: distanceMeters(here, [it.lat as number, it.lon as number]) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, 8);
  if (near.length === 0) return null;

  return (
    <div className="sheet__similar">
      <div className="sheet__similar-head">
        Рядом ещё
        <span className="recs__n">{near.length}</span>
      </div>
      <div className="simstrip">
        {near.map(({ it }) => {
          const dist = it.lat != null && it.lon != null ? distanceLabel(userPos, [it.lat, it.lon]) : null;
          return (
            <button key={it.event_id} type="button" className="simcard" onClick={() => onSelect(it)}>
              <span className="simcard__cover">
                <CategoryIcon cat={it.category} size={30} />
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

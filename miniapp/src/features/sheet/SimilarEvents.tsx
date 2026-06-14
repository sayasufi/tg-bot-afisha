import type { EventItem } from "../../api/client";
import { distanceMeters, type LatLon } from "../../lib/distance";
import { EventRow } from "../panel/EventRow";

// "Рядом ещё" — the closest other events to the one being viewed, so the user
// can chain to the next thing nearby without going back to the map.
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
    .slice(0, 4);
  if (near.length === 0) return null;

  return (
    <div className="sheet__similar">
      <div className="recs__section">
        Рядом ещё
        <span className="recs__n">{near.length}</span>
      </div>
      {near.map(({ it }, i) => (
        <EventRow key={it.event_id} item={it} index={i} userPos={userPos} onSelect={onSelect} />
      ))}
    </div>
  );
}

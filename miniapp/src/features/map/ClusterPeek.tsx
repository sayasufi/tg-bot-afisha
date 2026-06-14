import type { EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { EventRow } from "../panel/EventRow";

// A mini-list that peeks up when a cluster of events sits on one point (a venue
// stacked with several events, or a knot the map can't zoom apart). Lists the
// events so you can pick one without losing the map underneath.
export function ClusterPeek({
  events,
  userPos,
  onSelect,
  onClose,
}: {
  events: EventItem[] | null;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const open = !!events && events.length > 0;
  const list = events ?? [];
  const venue = list.find((e) => e.venue)?.venue ?? null;

  return (
    <div className={`peek${open ? " peek--open" : ""}`} aria-hidden={!open}>
      <button type="button" className="peek__scrim" aria-label="Закрыть" tabIndex={-1} onClick={onClose} />
      <div className="peek__panel" role="dialog" aria-modal="true">
        <span className="csheet__grip" />
        <div className="peek__head">
          <span className="peek__title">
            {list.length} {plural(list.length)}
            {venue ? <span className="peek__venue"> · {venue}</span> : null}
          </span>
          <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={18} />
          </button>
        </div>
        <div className="peek__scroll">
          {list.map((it, i) => (
            <EventRow key={it.event_id} item={it} index={i} userPos={userPos} onSelect={onSelect} />
          ))}
        </div>
      </div>
    </div>
  );
}

function plural(n: number): string {
  const d = n % 10;
  const dd = n % 100;
  if (d === 1 && dd !== 11) return "событие";
  if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return "события";
  return "событий";
}

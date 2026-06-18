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
  now,
  onSelect,
  onOpenVenue,
  onClose,
}: {
  events: EventItem[] | null;
  userPos?: LatLon | null;
  now?: number;
  onSelect: (i: EventItem) => void;
  onOpenVenue?: (venueId: number) => void;
  onClose: () => void;
}) {
  const open = !!events && events.length > 0;
  const list = events ?? [];
  // Show (and link) the venue ONLY when the whole cluster is one venue. A single map point
  // can stack several venues in one building, so labelling all of them with the first
  // venue's name — and its event count — is misleading (the venue page would then show
  // fewer events than the peek claimed, e.g. "20 · Волшебная лампа" vs 6 on the page).
  const venueIds = new Set(list.map((e) => e.venue_id).filter((v): v is number => v != null));
  const oneVenue = venueIds.size === 1;
  const venue = oneVenue ? list.find((e) => e.venue)?.venue ?? null : null;
  const venueId = oneVenue ? list.find((e) => e.venue_id != null)?.venue_id ?? null : null;

  return (
    <div className={`peek${open ? " peek--open" : ""}`} aria-hidden={!open}>
      <button type="button" className="peek__scrim" aria-label="Закрыть" tabIndex={-1} onClick={onClose} />
      <div className="peek__panel" role="dialog" aria-modal="true">
        <span className="csheet__grip" />
        <div className="peek__head">
          <span className="peek__title">
            {list.length} {plural(list.length)}
            {venue ? (
              <span className="peek__venue">
                {" · "}
                {venueId != null && onOpenVenue ? (
                  <button type="button" className="peek__venuebtn" onClick={() => onOpenVenue(venueId)}>
                    {venue}
                    <span className="peek__chev" aria-hidden="true">→</span>
                  </button>
                ) : (
                  venue
                )}
              </span>
            ) : null}
          </span>
          <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={18} />
          </button>
        </div>
        <div className="peek__scroll">
          {list.map((it, i) => (
            <EventRow key={it.event_id} item={it} index={i} userPos={userPos} now={now} onSelect={onSelect} />
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

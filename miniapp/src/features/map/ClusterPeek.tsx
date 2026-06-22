import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort, goNowState } from "../../lib/datetime";
import { distanceLabel, type LatLon } from "../../lib/distance";
import { CategoryIcon, IconClose, IconPin } from "../../lib/icons";

// One event row in the cluster peek — a framed «card-index» entry: the category in a hairline
// box, a cinnabar «live» dot, a lowercase title, a mono status line, distance + a chevron.
function ClusterRow({
  item,
  index,
  userPos,
  now,
  onSelect,
}: {
  item: EventItem;
  index: number;
  userPos?: LatLon | null;
  now?: number;
  onSelect: (i: EventItem) => void;
}) {
  const dist = item.lat != null && item.lon != null ? distanceLabel(userPos, [item.lat, item.lon]) : null;
  // Same predicate that reddens the map pin, off the SAME minute-tick, so the list never disagrees.
  const go = goNowState(item.date_start, item.date_end, item.open_now, now ? new Date(now) : new Date());
  const when = formatWhenShort(item.date_start, item.date_end);
  return (
    <button type="button" className="crow" style={{ "--i": index } as CSSProperties} onClick={() => onSelect(item)}>
      <span className="crow__box" aria-hidden="true">
        <CategoryIcon cat={item.category} size={22} />
      </span>
      <span className="crow__body">
        <span className="crow__title">
          {go.eligible && <i className="crow__dot" aria-hidden="true" />}
          {item.title || "Событие"}
        </span>
        <span className="crow__meta">
          {go.eligible && <span className="crow__live">{go.kind === "soon" ? go.label : "идёт сейчас"}</span>}
          {go.eligible ? " · " : ""}
          {when}
          {item.venue ? ` · ${item.venue}` : ""}
        </span>
      </span>
      {dist && <span className="crow__dist">{dist}</span>}
      <svg className="crow__chev" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

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
          <div className="peek__heading">
            <span className="peek__count">
              {list.length} {plural(list.length)}
            </span>
            {venue ? (
              venueId != null && onOpenVenue ? (
                <button type="button" className="peek__venue peek__venue--btn" onClick={() => onOpenVenue(venueId)}>
                  <IconPin size={13} className="peek__pin" />
                  <span className="peek__venuename">{venue}</span>
                </button>
              ) : (
                <span className="peek__venue">
                  <IconPin size={13} className="peek__pin" />
                  <span className="peek__venuename">{venue}</span>
                </span>
              )
            ) : null}
          </div>
          <button type="button" className="peek__close" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={18} />
          </button>
        </div>
        <div className="peek__scroll">
          {list.map((it, i) => (
            <ClusterRow key={it.event_id} item={it} index={i} userPos={userPos} now={now} onSelect={onSelect} />
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

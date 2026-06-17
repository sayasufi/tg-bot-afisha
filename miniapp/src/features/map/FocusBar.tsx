import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort, goNowState } from "../../lib/datetime";
import { IconClose } from "../../lib/icons";

// A slim "wall label" that floats at the bottom while a marker is highlighted:
// a tiny uppercase category·date kicker over the title (display font, lowercase),
// marked with the one acid tag. When the event is one you can still get to, the
// tag turns cinnabar and the kicker leads with a live countdown ("через 1 ч"
// / "идёт сейчас"). Tap to reopen, × to drop the selection.
export function FocusBar({
  event,
  out,
  now,
  onOpen,
  onClose,
}: {
  event: EventItem;
  out?: boolean;
  now?: number;
  onOpen: (i: EventItem) => void;
  onClose: () => void;
}) {
  const meta = categoryMeta(event.category);
  const when = formatWhenShort(event.date_start, event.date_end);
  const go = goNowState(event.date_start, event.date_end, event.open_now, now ? new Date(now) : new Date());
  return (
    <div className={`focusbar${out ? " focusbar--out" : ""}`}>
      <button type="button" className="focusbar__main" onClick={() => onOpen(event)}>
        <span className={`focusbar__tag${go.eligible ? " focusbar__tag--live" : ""}`} aria-hidden="true" />
        <span className="focusbar__text">
          <span className="focusbar__kicker">
            {go.eligible && <span className="focusbar__live">{go.kind === "soon" ? go.label : "идёт сейчас"} · </span>}
            {meta.label}
            {when ? ` · ${when}` : ""}
          </span>
          <span className="focusbar__title">{event.title}</span>
        </span>
      </button>
      <button type="button" className="focusbar__close" aria-label="Снять выделение" onClick={onClose}>
        <IconClose size={15} />
      </button>
    </div>
  );
}

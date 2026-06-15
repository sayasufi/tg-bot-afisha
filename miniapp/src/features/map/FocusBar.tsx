import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort } from "../../lib/datetime";
import { IconClose } from "../../lib/icons";

// A slim "wall label" that floats at the bottom while a marker is highlighted:
// a tiny uppercase category·date kicker over the title (display font, lowercase),
// marked with the one acid tag. Tap to reopen, × to drop the selection.
export function FocusBar({ event, out, onOpen, onClose }: { event: EventItem; out?: boolean; onOpen: (i: EventItem) => void; onClose: () => void }) {
  const meta = categoryMeta(event.category);
  const when = formatWhenShort(event.date_start, event.date_end);
  return (
    <div className={`focusbar${out ? " focusbar--out" : ""}`}>
      <button type="button" className="focusbar__main" onClick={() => onOpen(event)}>
        <span className="focusbar__tag" aria-hidden="true" />
        <span className="focusbar__text">
          <span className="focusbar__kicker">
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

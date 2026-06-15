import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort } from "../../lib/datetime";
import { CategoryIcon, IconClose } from "../../lib/icons";

// A slim bar that sits at the bottom while a marker is highlighted on the map:
// tap it to reopen the event, × to drop the selection. Carries the one accent
// (acid hairline) so it reads as "the marked exhibit".
export function FocusBar({ event, out, onOpen, onClose }: { event: EventItem; out?: boolean; onOpen: (i: EventItem) => void; onClose: () => void }) {
  const meta = categoryMeta(event.category);
  const when = formatWhenShort(event.date_start, event.date_end);
  return (
    <div className={`focusbar${out ? " focusbar--out" : ""}`} style={{ "--cat": meta.color } as CSSProperties}>
      <button type="button" className="focusbar__main" onClick={() => onOpen(event)}>
        <span className="focusbar__cat">
          <CategoryIcon cat={event.category} size={17} />
        </span>
        <span className="focusbar__text">
          <span className="focusbar__title">{event.title}</span>
          {when && <span className="focusbar__meta">{when}</span>}
        </span>
      </button>
      <button type="button" className="focusbar__close" aria-label="Снять выделение" onClick={onClose}>
        <IconClose size={16} />
      </button>
    </div>
  );
}

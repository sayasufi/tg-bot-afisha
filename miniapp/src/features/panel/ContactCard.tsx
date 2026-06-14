import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort } from "../../lib/datetime";
import { CategoryIcon } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";

// Contact-sheet cell — a duotone thumbnail with a mono caption + accession
// number, the gallery-catalogue grid view (variant.com editorial mode).
export function ContactCard({ item, index, onSelect }: { item: EventItem; index: number; onSelect: (i: EventItem) => void }) {
  const img = safeHttpUrl(item.primary_image_url);
  return (
    <button type="button" className="ccard" style={{ "--i": index } as CSSProperties} onClick={() => onSelect(item)}>
      <span className="ccard__cover">
        {img ? <img src={img} alt="" loading="lazy" decoding="async" /> : <CategoryIcon cat={item.category} size={30} className="ccard__glyph" />}
        <span className="ccard__no">{String(index + 1).padStart(2, "0")}</span>
      </span>
      <span className="ccard__title">{item.title}</span>
      <span className="ccard__meta">{formatWhenShort(item.date_start, item.date_end)}</span>
    </button>
  );
}

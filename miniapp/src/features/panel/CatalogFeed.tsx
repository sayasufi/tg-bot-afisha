import { type CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { formatWhenShort, goNowState } from "../../lib/datetime";
import type { LatLon } from "../../lib/distance";
import { CategoryIcon } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";

function priceLabel(p: number | null | undefined): string | null {
  if (p == null) return null;
  if (p <= 0) return "бесплатно";
  return `от ${Math.round(p).toLocaleString("ru-RU")} ₽`;
}

type Card = {
  item: EventItem;
  img: string;
  code: string | null;
  title: string;
  meta: string;
  venue: string | null;
  price: string | null;
  free: boolean;
  go: ReturnType<typeof goNowState>;
};

function derive(item: EventItem, now?: number): Card {
  const nowDate = now != null ? new Date(now) : undefined;
  const when = formatWhenShort(item.date_start, item.date_end, nowDate);
  const price = priceLabel(item.price_min);
  return {
    item,
    img: safeHttpUrl(item.primary_image_url) || "",
    code: item.code ?? null,
    title: item.title,
    meta: [when, item.venue].filter(Boolean).join(" · "),
    venue: item.venue ?? null,
    price,
    free: price === "бесплатно",
    go: goNowState(item.date_start, item.date_end, item.open_now, nowDate),
  };
}

// Every card is a photo block now; the look is one of several stylish "variants" that
// rotate so adjacent cards never repeat. The metadata footer is laid out by variant.
type Variant = "bottomrow" | "bottomstack" | "sideblack" | "band" | "tall";
const FULL_VARIANTS: Variant[] = ["bottomrow", "sideblack", "tall", "band"];
const HALF_VARIANTS: Variant[] = ["bottomstack", "band", "tall", "bottomstack"];
const ROWS = ["full", "duo", "full", "full", "duo"] as const;

// stacked-footer variants show venue over price; row variants show when·venue then price.
const STACK = new Set<Variant>(["bottomstack", "sideblack", "tall"]);

function PhotoCard({
  c,
  width,
  variant,
  onSelect,
}: {
  c: Card;
  width: "full" | "half";
  variant: Variant;
  onSelect: (i: EventItem) => void;
}) {
  const stack = STACK.has(variant);
  return (
    <button
      type="button"
      className={`cat cat--${width} cat--${variant}${c.img ? "" : " cat--noimg"}`}
      onClick={() => onSelect(c.item)}
    >
      {c.img ? (
        <>
          <img className="cat__img" src={c.img} alt="" loading="lazy" decoding="async" />
          <span className="poster-grain" aria-hidden="true" />
        </>
      ) : (
        <span className="cat__glyph">
          <CategoryIcon cat={c.item.category} size={52} />
        </span>
      )}
      <span className="cat__scrim" aria-hidden="true" />
      {c.code && (
        <span className="cat__code">
          <CategoryIcon cat={c.item.category} size={13} />
          {c.code}
        </span>
      )}
      <span className="cat__panel">
        {c.go.eligible && (
          <span className="cat__live">{c.go.kind === "soon" ? c.go.label : "идёт сейчас"}</span>
        )}
        <span className="cat__title">{c.title}</span>
        <span className={`cat__foot${stack ? " cat__foot--col" : ""}`}>
          {(stack ? c.venue : c.meta) && <span className="cat__meta">{stack ? c.venue : c.meta}</span>}
          {c.price && <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>}
        </span>
      </span>
    </button>
  );
}

export function CatalogFeed({
  items,
  now,
  onSelect,
}: {
  items: EventItem[];
  userPos?: LatLon | null;
  now?: number;
  onSelect: (i: EventItem) => void;
}) {
  type Slot = { c: Card; variant: Variant };
  const rows: { kind: "full" | "duo"; slots: Slot[]; key: string }[] = [];
  let i = 0;
  let r = 0;
  let fullN = 0;
  let halfN = 0;
  while (i < items.length) {
    const rt = ROWS[r % ROWS.length];
    if (rt === "duo" && i + 1 < items.length) {
      const c1 = derive(items[i], now);
      const c2 = derive(items[i + 1], now);
      rows.push({
        kind: "duo",
        slots: [
          { c: c1, variant: HALF_VARIANTS[halfN++ % HALF_VARIANTS.length] },
          { c: c2, variant: HALF_VARIANTS[halfN++ % HALF_VARIANTS.length] },
        ],
        key: c1.item.event_id,
      });
      i += 2;
    } else {
      const c = derive(items[i], now);
      rows.push({
        kind: "full",
        slots: [{ c, variant: FULL_VARIANTS[fullN++ % FULL_VARIANTS.length] }],
        key: c.item.event_id,
      });
      i += 1;
    }
    r += 1;
  }

  return (
    <div className="catalog">
      {rows.map((row, ri) => (
        <div
          className={`catalog__row${row.kind === "duo" ? " catalog__row--duo" : ""}`}
          style={{ "--i": Math.min(ri, 8) } as CSSProperties}
          key={row.key}
        >
          {row.slots.map((s) => (
            <PhotoCard
              key={s.c.item.event_id}
              c={s.c}
              width={row.kind === "duo" ? "half" : "full"}
              variant={s.variant}
              onSelect={onSelect}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

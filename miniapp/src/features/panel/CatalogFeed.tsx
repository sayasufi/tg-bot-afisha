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
  when: string;
  venue: string | null;
  price: string | null;
  free: boolean;
  go: ReturnType<typeof goNowState>;
};

function derive(item: EventItem, now?: number): Card {
  const nowDate = now != null ? new Date(now) : undefined;
  const price = priceLabel(item.price_min);
  return {
    item,
    img: safeHttpUrl(item.primary_image_url) || "",
    code: item.code ?? null,
    title: item.title,
    when: formatWhenShort(item.date_start, item.date_end, nowDate),
    venue: item.venue ?? null,
    price,
    free: price === "бесплатно",
    go: goNowState(item.date_start, item.date_end, item.open_now, nowDate),
  };
}

// Every card is a photo block; the look is one of several variants that rotate so adjacent
// cards never repeat. Transitions fade to black / white / acid, from bottom / right / top.
type Variant = "bottom" | "sideblack" | "band" | "tall" | "whiteband" | "acidband" | "topband";
const FULL_VARIANTS: Variant[] = ["bottom", "sideblack", "whiteband", "tall", "band", "acidband", "topband"];
const HALF_VARIANTS: Variant[] = ["bottom", "whiteband", "band", "acidband"];
const ROWS = ["full", "duo", "full", "full", "duo"] as const;
// A hairline rule between title and footer — drawn on some cards, not others (rotates).
const RULED = [false, true, true, false, true, false];

function PhotoCard({
  c,
  width,
  variant,
  ruled,
  onSelect,
}: {
  c: Card;
  width: "full" | "half";
  variant: Variant;
  ruled: boolean;
  onSelect: (i: EventItem) => void;
}) {
  return (
    <button
      type="button"
      className={`cat cat--${width} cat--${variant}${ruled ? " cat--ruled" : ""}${c.img ? "" : " cat--noimg"}`}
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
        <span className="cat__foot">
          {c.when && <span className="cat__when">{c.when}</span>}
          {(c.venue || c.price) && (
            <span className="cat__sub">
              {c.venue && <span className="cat__venue">{c.venue}</span>}
              {c.price && <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>}
            </span>
          )}
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
  type Slot = { c: Card; variant: Variant; ruled: boolean };
  const rows: { kind: "full" | "duo"; slots: Slot[]; key: string }[] = [];
  let i = 0;
  let r = 0;
  let fullN = 0;
  let halfN = 0;
  let cardN = 0;
  const ruled = () => RULED[cardN++ % RULED.length];
  while (i < items.length) {
    const rt = ROWS[r % ROWS.length];
    if (rt === "duo" && i + 1 < items.length) {
      const c1 = derive(items[i], now);
      const c2 = derive(items[i + 1], now);
      rows.push({
        kind: "duo",
        slots: [
          { c: c1, variant: HALF_VARIANTS[halfN++ % HALF_VARIANTS.length], ruled: ruled() },
          { c: c2, variant: HALF_VARIANTS[halfN++ % HALF_VARIANTS.length], ruled: ruled() },
        ],
        key: c1.item.event_id,
      });
      i += 2;
    } else {
      const c = derive(items[i], now);
      rows.push({
        kind: "full",
        slots: [{ c, variant: FULL_VARIANTS[fullN++ % FULL_VARIANTS.length], ruled: ruled() }],
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
              ruled={s.ruled}
              onSelect={onSelect}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

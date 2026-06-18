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
  meta: string;
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
    when,
    venue: item.venue ?? null,
    meta: [when, item.venue].filter(Boolean).join(" · "),
    price,
    free: price === "бесплатно",
    go: goNowState(item.date_start, item.date_end, item.open_now, nowDate),
  };
}

// Shared bits ---------------------------------------------------------------
function Code({ c }: { c: Card }) {
  return c.code ? (
    <span className="cat__code">
      <CategoryIcon cat={c.item.category} size={13} />
      {c.code}
    </span>
  ) : null;
}

function Live({ c }: { c: Card }) {
  return c.go.eligible ? (
    <span className="cat__live">{c.go.kind === "soon" ? c.go.label : "идёт сейчас"}</span>
  ) : null;
}

function Cover({ c }: { c: Card }) {
  return c.img ? (
    <>
      <img className="cat__img" src={c.img} alt="" loading="lazy" decoding="async" />
      <span className="poster-grain" aria-hidden="true" />
      <span className="cat__scrim" aria-hidden="true" />
    </>
  ) : (
    <span className="cat__glyph">
      <CategoryIcon cat={c.item.category} size={52} />
    </span>
  );
}

// Card variants -------------------------------------------------------------
function Hero({ c, onSelect }: { c: Card; onSelect: (i: EventItem) => void }) {
  return (
    <button type="button" className={`cat cat--hero${c.img ? "" : " cat--noimg"}`} onClick={() => onSelect(c.item)}>
      <Cover c={c} />
      <Code c={c} />
      <span className="cat__btm">
        <Live c={c} />
        <span className="cat__title cat__title--hero">{c.title}</span>
        <span className="cat__foot">
          {c.meta && <span className="cat__meta">{c.meta}</span>}
          {c.price && <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>}
        </span>
      </span>
    </button>
  );
}

function Photo({ c, onSelect }: { c: Card; onSelect: (i: EventItem) => void }) {
  return (
    <button type="button" className={`cat cat--photo${c.img ? "" : " cat--noimg"}`} onClick={() => onSelect(c.item)}>
      <Cover c={c} />
      <Code c={c} />
      <span className="cat__btm">
        <Live c={c} />
        <span className="cat__title cat__title--photo">{c.title}</span>
        <span className="cat__foot cat__foot--col">
          {c.venue && <span className="cat__meta">{c.venue}</span>}
          {c.price && <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>}
        </span>
      </span>
    </button>
  );
}

function Text({ c, onSelect }: { c: Card; onSelect: (i: EventItem) => void }) {
  return (
    <button type="button" className="cat cat--text" onClick={() => onSelect(c.item)}>
      <Code c={c} />
      <span className="cat__title cat__title--text">{c.title}</span>
      <span className="cat__textfoot">
        <span className="cat__metacol">
          {c.when && <span className="cat__meta">{c.when}</span>}
          {c.venue && <span className="cat__meta">{c.venue}</span>}
        </span>
        {c.price && (
          <span className="cat__pricego">
            <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>
            <span className="cat__arrow" aria-hidden="true">→</span>
          </span>
        )}
      </span>
    </button>
  );
}

function Wide({ c, onSelect }: { c: Card; onSelect: (i: EventItem) => void }) {
  return (
    <button type="button" className="cat cat--wide" onClick={() => onSelect(c.item)}>
      <Code c={c} />
      <span className="cat__widerow">
        <span className="cat__title cat__title--wide">{c.title}</span>
        {c.when && <span className="cat__when">{c.when}</span>}
      </span>
      <span className="cat__textfoot">
        <span className="cat__metacol">{c.venue && <span className="cat__meta">{c.venue}</span>}</span>
        {c.price && (
          <span className="cat__pricego">
            <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>
            <span className="cat__arrow" aria-hidden="true">→</span>
          </span>
        )}
      </span>
    </button>
  );
}

function Side({ c, onSelect }: { c: Card; onSelect: (i: EventItem) => void }) {
  return (
    <button type="button" className={`cat cat--side${c.img ? "" : " cat--noimg"}`} onClick={() => onSelect(c.item)}>
      <Cover c={c} />
      <Code c={c} />
      <span className="cat__sidetext">
        <Live c={c} />
        <span className="cat__title cat__title--side">{c.title}</span>
        <span className="cat__foot cat__foot--col">
          {c.meta && <span className="cat__meta">{c.meta}</span>}
          {c.price && <span className={`cat__price${c.free ? " cat__price--free" : ""}`}>{c.price}</span>}
        </span>
      </span>
    </button>
  );
}

// The catalogue rhythm: hero photo → duo[photo + text] → wide text → photo-side, repeating.
// One flat list of events is grouped into editorial rows that alternate photo / type blocks.
const PATTERN = ["hero", "duo", "wide", "side"] as const;

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
  const rows: { type: string; cards: Card[]; key: string }[] = [];
  let i = 0;
  let p = 0;
  while (i < items.length) {
    const type = PATTERN[p % PATTERN.length];
    if (type === "duo") {
      const cards = items.slice(i, i + 2).map((it) => derive(it, now));
      rows.push({ type, cards, key: cards[0].item.event_id });
      i += 2;
    } else {
      rows.push({ type, cards: [derive(items[i], now)], key: items[i].event_id });
      i += 1;
    }
    p += 1;
  }

  return (
    <div className="catalog">
      {rows.map((row, ri) => {
        const style = { "--i": Math.min(ri, 8) } as CSSProperties;
        if (row.type === "hero")
          return (
            <div className="catalog__row" style={style} key={row.key}>
              <Hero c={row.cards[0]} onSelect={onSelect} />
            </div>
          );
        if (row.type === "duo")
          return (
            <div className="catalog__row catalog__row--duo" style={style} key={row.key}>
              <Photo c={row.cards[0]} onSelect={onSelect} />
              {row.cards[1] ? <Text c={row.cards[1]} onSelect={onSelect} /> : null}
            </div>
          );
        if (row.type === "wide")
          return (
            <div className="catalog__row" style={style} key={row.key}>
              <Wide c={row.cards[0]} onSelect={onSelect} />
            </div>
          );
        return (
          <div className="catalog__row" style={style} key={row.key}>
            <Side c={row.cards[0]} onSelect={onSelect} />
          </div>
        );
      })}
    </div>
  );
}

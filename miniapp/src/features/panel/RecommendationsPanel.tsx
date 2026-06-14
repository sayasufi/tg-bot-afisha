import { useMemo, useState, type CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { eventBucket } from "../../lib/datetime";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { hapticSelection } from "../../lib/telegram";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { EventRow } from "./EventRow";
import { PullHint } from "./PullHint";

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 7 }).map((_, i) => (
        <div key={i} className="erow erow--skel" style={{ "--i": i } as CSSProperties}>
          <span className="erow__mark" />
          <span className="erow__body">
            <span className="skel skel--title" />
            <span className="skel skel--meta" />
          </span>
        </div>
      ))}
    </>
  );
}

type Seg = "today" | "week" | "all";
const SEGMENTS: { key: Seg; label: string; maxOrder: number }[] = [
  { key: "today", label: "Сегодня", maxOrder: 1 },
  { key: "week", label: "Неделя", maxOrder: 2 },
  { key: "all", label: "Всё", maxOrder: 99 },
];

export function RecommendationsPanel({
  items,
  query,
  userPos,
  favCategories = [],
  loading = false,
  onRefresh,
  onSelect,
  onClose,
}: {
  items: EventItem[];
  query?: string;
  userPos?: LatLon | null;
  favCategories?: string[];
  loading?: boolean;
  onRefresh?: () => void;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const ptr = usePullToRefresh(() => onRefresh?.());
  const [seg, setSeg] = useState<Seg>("all");
  const maxOrder = SEGMENTS.find((s) => s.key === seg)!.maxOrder;

  const sorted = useMemo(
    () => [...items].sort((a, b) => (a.date_start || "").localeCompare(b.date_start || "")),
    [items],
  );

  // Time buckets, filtered by the active segment (Сегодня / Неделя / Всё). The
  // "ongoing"/"perm" buckets (order 4/5) only show under "Всё".
  const ordered = useMemo(() => {
    const groups = new Map<number, { label: string; items: EventItem[] }>();
    for (const it of sorted) {
      const b = eventBucket(it.date_start, it.date_end);
      if (b.order > maxOrder) continue;
      let g = groups.get(b.order);
      if (!g) {
        g = { label: b.label, items: [] };
        groups.set(b.order, g);
      }
      g.items.push(it);
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([, g]) => g);
  }, [sorted, maxOrder]);

  // "Для тебя" — soonest events in your favourite categories, within the
  // selected window. Pure boost of what you already like; capped to a peek.
  const forYou = useMemo(() => {
    if (favCategories.length === 0) return [];
    const set = new Set(favCategories);
    return sorted.filter((it) => set.has(it.category) && eventBucket(it.date_start, it.date_end).order <= maxOrder).slice(0, 6);
  }, [sorted, favCategories, maxOrder]);

  let idx = 0;
  const empty = ordered.length === 0 && forYou.length === 0;

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Рекомендации</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="seg">
        {SEGMENTS.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`seg__btn${seg === s.key ? " seg__btn--active" : ""}`}
            onClick={() => {
              hapticSelection();
              setSeg(s.key);
            }}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {empty && (loading ? <SkeletonRows /> : <p className="panelview__empty">Пока нечего показать</p>)}

        {forYou.length > 0 && (
          <section>
            <div className="recs__section recs__section--you">
              Для тебя
              <span className="recs__n">{forYou.length}</span>
            </div>
            {forYou.map((it) => (
              <EventRow key={`you-${it.event_id}`} item={it} index={idx++} query={query} userPos={userPos} onSelect={onSelect} />
            ))}
          </section>
        )}

        {ordered.map((g) => (
          <section key={g.label}>
            <div className="recs__section">
              {g.label}
              <span className="recs__n">{g.items.length}</span>
            </div>
            {g.items.map((it) => (
              <EventRow key={it.event_id} item={it} index={idx++} query={query} userPos={userPos} onSelect={onSelect} />
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

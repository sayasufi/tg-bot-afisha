import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { eventBucket } from "../../lib/datetime";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
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

export function RecommendationsPanel({
  items,
  query,
  userPos,
  loading = false,
  onRefresh,
  onSelect,
  onClose,
}: {
  items: EventItem[];
  query?: string;
  userPos?: LatLon | null;
  loading?: boolean;
  onRefresh?: () => void;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const ptr = usePullToRefresh(() => onRefresh?.());
  const sorted = [...items].sort((a, b) => (a.date_start || "").localeCompare(b.date_start || ""));
  // Group into time buckets (Сегодня / На этой неделе / Позже / Идут сейчас / Постоянно).
  const groups = new Map<number, { label: string; items: EventItem[] }>();
  for (const it of sorted) {
    const b = eventBucket(it.date_start, it.date_end);
    let g = groups.get(b.order);
    if (!g) {
      g = { label: b.label, items: [] };
      groups.set(b.order, g);
    }
    g.items.push(it);
  }
  const ordered = [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([, g]) => g);
  let idx = 0;

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Рекомендации</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {ordered.length === 0 &&
          (loading ? <SkeletonRows /> : <p className="panelview__empty">Пока нечего показать</p>)}
        {ordered.map((g) => (
          <section key={g.label}>
            <div className="recs__section">
              {g.label}
              <span className="recs__n">{g.items.length}</span>
            </div>
            {g.items.map((it) => {
              const i = idx++;
              return (
                <EventRow
                  key={it.event_id}
                  item={it}
                  index={i}
                  query={query}
                  userPos={userPos}
                  onSelect={onSelect}
                />
              );
            })}
          </section>
        ))}
      </div>
    </div>
  );
}

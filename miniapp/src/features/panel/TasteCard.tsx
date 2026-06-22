import { useMemo } from "react";

import { type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { CategoryIcon } from "../../lib/icons";

// Pixel offset from the box centre for circle i of n, by share rank — a tight OVERLAPPING RING with a
// touch of spiral: the dominant leads up-left, each circle overlaps its neighbours, the radius grows a
// hair per step. PX (not %) so it never stretches/clips on a wide box.
function clusterPos(i: number, n: number): { dx: number; dy: number } {
  const step = (2 * Math.PI) / Math.max(n, 3);
  const angle = -2.2 + i * step;
  const p = 48 + i * 4; // ring radius px, slight growth = spiral
  return { dx: Math.cos(angle) * p * 1.1, dy: Math.sin(angle) * p };
}

const eventsBasis = (n: number) => `основано на ${n} ${n === 1 ? "сохранённом событии" : "сохранённых событиях"}`;

// «Вкус» — a constellation of category circles (one per genre, sized by share) computed from a set of
// saved events. Reused by your own Profile (tappable → Избранное) and a friend's profile (a static viz of
// their taste, the same «кружочки»). `onTap` omitted → renders as a non-interactive card.
export function TasteCard({ events, title, onTap }: { events: EventItem[]; title: string; onTap?: () => void }) {
  const taste = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of events) counts.set(it.category, (counts.get(it.category) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([key, n]) => ({ key, n, meta: categoryMeta(key) }));
  }, [events]);
  const hasTaste = events.length > 0;

  const inner = (
    <>
      <span className="tastecard__head">
        <span className="tastecard__title">{title}</span>
        {onTap && (
          <span className="tastecard__chev" aria-hidden="true">
            →
          </span>
        )}
      </span>
      {hasTaste ? (
        <>
          <span className="tastecard__cluster">
            {taste.slice(0, 6).map((t, i, arr) => {
              const d = 64 + Math.round((t.n / arr[0].n) * 28); // 64..92px, by genre share
              const pos = clusterPos(i, arr.length);
              const top = i === 0;
              return (
                <span
                  key={t.key}
                  className={`tcircle${top ? " tcircle--top" : ""}`}
                  style={{
                    width: `${d}px`,
                    height: `${d}px`,
                    left: `calc(50% + ${pos.dx}px)`,
                    top: `calc(50% + ${pos.dy}px)`,
                    zIndex: top ? 20 : i + 1,
                  }}
                >
                  <CategoryIcon cat={t.key} size={Math.round(d * 0.28)} />
                  <span className="tcircle__label">{t.meta.label.toLowerCase()}</span>
                  <span className="tcircle__n">{t.n}</span>
                </span>
              );
            })}
            {/* Accent dots fill the gaps — the «constellation» finish. */}
            <span className="tdot tdot--acid" style={{ left: "84%", top: "18%" }} />
            <span className="tdot" style={{ left: "14%", top: "26%" }} />
            <span className="tdot tdot--acid" style={{ left: "76%", top: "84%" }} />
            <span className="tdot" style={{ left: "26%", top: "86%" }} />
          </span>
          <span className="tastecard__basis">{eventsBasis(events.length)}</span>
        </>
      ) : (
        <>
          <span className="tastecard__nudge">
            Пока ничего нет. Сохрани несколько событий — и здесь сложится твой культурный профиль.
          </span>
          <span className="tastecard__cluster">
            {[86, 70, 74, 64, 68].map((d, i) => {
              const pos = clusterPos(i, 5);
              return (
                <span
                  key={i}
                  className="tcircle tcircle--empty"
                  style={{ width: `${d}px`, height: `${d}px`, left: `calc(50% + ${pos.dx}px)`, top: `calc(50% + ${pos.dy}px)` }}
                />
              );
            })}
          </span>
        </>
      )}
    </>
  );

  return onTap ? (
    <button type="button" className="tastecard" aria-label={`${title} — открыть избранное`} onClick={onTap}>
      {inner}
    </button>
  ) : (
    <div className="tastecard tastecard--static">{inner}</div>
  );
}

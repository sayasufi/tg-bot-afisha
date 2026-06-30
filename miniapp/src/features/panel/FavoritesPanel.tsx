import { useEffect, useState } from "react";

import { fetchEventsByIds, type EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconHeart } from "../../lib/icons";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { CatalogFeed } from "./CatalogFeed";
import { PullHint } from "./PullHint";

// Favourites — fetched by id from the server (independent of the map's loaded set, so the
// list always matches the count), in the same full-bleed poster format as the list view.
export function FavoritesPanel({
  favIds,
  userPos,
  onSelect,
  onClose,
  onBrowseWeekend,
}: {
  favIds: Set<string>;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
  onBrowseWeekend?: () => void;
}) {
  const [favs, setFavs] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showPast, setShowPast] = useState(false);
  const idsKey = [...favIds].sort().join(",");

  const load = () => {
    const ids = idsKey ? idsKey.split(",") : [];
    setError(false);
    if (!ids.length) {
      setFavs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchEventsByIds(ids, userPos ?? null)
      .then((r) => {
        setFavs(r);
        setLoading(false);
      })
      // A failed fetch is NOT an empty favourites list — keep the count, show a retry.
      .catch(() => {
        setLoading(false);
        setError(true);
      });
  };
  // Mounted only while the favourites view is open; (re)fetch on open and when the set changes.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const ptr = usePullToRefresh(() => load());

  // Прошедшие сейвы не должны висеть навсегда поводом-без-повода: вверху — актуальные (ещё идут/впереди),
  // прошедшие — под катом «Прошедшие · N», чтобы не загромождать и не путать («это уже было»).
  const nowMs = Date.now();
  const isPast = (e: EventItem) => {
    const end = Date.parse(e.date_end || e.date_start);
    return Number.isFinite(end) && end < nowMs;
  };
  const upcoming = favs.filter((e) => !isPast(e));
  const past = favs.filter(isPast);

  return (
    <div className="panelview listview">
      <header className="panelview__head">
        <h2>избранное</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {favs.length > 0 ? (
          <>
            {upcoming.length > 0 && <CatalogFeed items={upcoming} userPos={userPos} onSelect={onSelect} />}
            {upcoming.length === 0 && past.length > 0 && (
              <p className="panelview__hint" style={{ padding: "16px" }}>
                Все сохранённые события уже прошли. {onBrowseWeekend ? "Загляни в афишу — найдётся новое." : ""}
              </p>
            )}
            {past.length > 0 && (
              <div style={{ borderTop: "1px solid var(--line)", marginTop: upcoming.length ? 8 : 0 }}>
                <button
                  type="button"
                  onClick={() => setShowPast((v) => !v)}
                  style={{ width: "100%", textAlign: "left", padding: "12px 16px", background: "none", border: 0,
                    color: "var(--ink-dim)", font: "inherit", cursor: "pointer", display: "flex", justifyContent: "space-between" }}
                >
                  <span>Прошедшие · {past.length}</span>
                  <span>{showPast ? "▴" : "▾"}</span>
                </button>
                {showPast && <CatalogFeed items={past} userPos={userPos} onSelect={onSelect} />}
              </div>
            )}
          </>
        ) : loading ? null : error ? (
          <div className="favempty">
            <p className="panelview__hint">Не удалось загрузить избранное. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary" onClick={load}>
              Повторить
            </button>
          </div>
        ) : (
          <div className="favempty">
            <IconHeart size={40} className="favempty__glyph" />
            <p className="panelview__hint">
              Отмечай события сердечком в карточке — они соберутся здесь, чтобы вернуться к ним позже.
            </p>
            {onBrowseWeekend && (
              <button type="button" className="btn btn--primary" onClick={onBrowseWeekend}>
                Афиша на выходные →
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

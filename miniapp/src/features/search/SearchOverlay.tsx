import { useEffect, useRef, useState } from "react";

import { searchEvents, type EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconSearch } from "../../lib/icons";
import { EventRow } from "../panel/EventRow";

// Looks like a public event code ("MSK-04PN") → fire immediately (no debounce, no min
// length), since the user pasted an exact id. Mirrors the server's _looks_like_code.
const CODE_RE = /^[A-Za-z]{2,4}[-·\s]?[0-9A-Za-z]{2,8}$/;
const looksLikeCode = (s: string) => CODE_RE.test(s) && (s.includes("-") || /\d/.test(s));

// Full-screen typeahead over the map: search events by code / title / venue with a live
// ranked dropdown. Debounced + aborted so fast typing never races. Opens an event sheet
// on tap (with no extra fetch — rows carry coords/date).
export function SearchOverlay({
  open,
  city,
  userPos,
  onSelect,
  onClose,
}: {
  open: boolean;
  city?: string | null;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset + focus on open.
  useEffect(() => {
    if (!open) return;
    setQ("");
    setItems([]);
    setLoading(false);
    const t = setTimeout(() => inputRef.current?.focus(), 60);
    return () => clearTimeout(t);
  }, [open]);

  // Debounced, abortable fetch. Code-shaped queries fire instantly; everything else
  // waits 250 ms and needs ≥2 chars.
  useEffect(() => {
    if (!open) return;
    const s = q.trim();
    const code = looksLikeCode(s);
    if (s.length < 2 && !code) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      searchEvents(s, city, ctrl.signal)
        .then((r) => {
          setItems(r);
          setLoading(false);
        })
        .catch((e) => {
          if (e?.name !== "AbortError") {
            setItems([]);
            setLoading(false);
          }
        });
    }, code ? 0 : 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, city, open]);

  if (!open) return null;
  const s = q.trim();
  const showEmpty = !loading && s.length >= 2 && items.length === 0;

  return (
    <div className="searchov" role="dialog" aria-modal="true" aria-label="Поиск">
      <button type="button" className="searchov__scrim" aria-label="Закрыть" onClick={onClose} />
      {loading && <div className="searchov__loading" aria-hidden="true" />}
      <div className="searchov__panel">
        <div className="search searchov__bar">
          <IconSearch className="search__glyph" size={18} />
          <input
            ref={inputRef}
            className="search__input"
            placeholder="Событие, место или код…"
            value={q}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "Enter" && items[0]) {
                onSelect(items[0]);
                onClose();
              }
            }}
          />
          <button type="button" className="search__clear" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={16} />
          </button>
        </div>

        {(items.length > 0 || showEmpty) && (
          <div className="searchov__results">
            {items.map((it, i) => (
              <EventRow
                key={it.event_id}
                item={it}
                index={i}
                query={s}
                userPos={userPos}
                onSelect={(x) => {
                  onSelect(x);
                  onClose();
                }}
              />
            ))}
            {showEmpty && <div className="searchov__empty">Ничего не найдено</div>}
          </div>
        )}
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";

import { searchEvents, type EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconSearch } from "../../lib/icons";
import { useFocusTrap } from "../../lib/useFocusTrap";
import { EventRow } from "../panel/EventRow";

// Looks like a public event code ("MSK-04PN") → fire immediately (no debounce, no min
// length), since the user pasted an exact id. Mirrors the server's _looks_like_code.
const CODE_RE = /^[A-Za-z]{2,4}[-·\s]?[0-9A-Za-z]{2,8}$/;
const looksLikeCode = (s: string) => CODE_RE.test(s) && (s.includes("-") || /\d/.test(s));

// Empty-state helpers: recent queries (per-device) + example chips, so a blank search isn't a dead end.
const RECENT_KEY = "search:recent";
const SUGGESTIONS = ["концерт", "выставка", "стендап", "театр", "вечеринка", "экскурсия"];

function loadRecent(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}
function pushRecent(q: string): void {
  const s = q.trim();
  if (s.length < 2 || looksLikeCode(s)) return; // don't stash codes / stray chars
  try {
    const cur = loadRecent().filter((x) => x.toLowerCase() !== s.toLowerCase());
    localStorage.setItem(RECENT_KEY, JSON.stringify([s, ...cur].slice(0, 6)));
  } catch {
    /* private mode / quota — recent is a nicety, never block search */
  }
}

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
  const [error, setError] = useState(false);
  const [active, setActive] = useState(-1); // keyboard-highlighted result (-1 = none)
  const [recent, setRecent] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  useFocusTrap(overlayRef, open, inputRef); // trap focus in the overlay; land on the search input

  // Reset + focus on open.
  useEffect(() => {
    if (!open) return;
    setQ("");
    setItems([]);
    setLoading(false);
    setError(false);
    setActive(-1);
    setRecent(loadRecent());
    const t = setTimeout(() => inputRef.current?.focus(), 60);
    return () => clearTimeout(t);
  }, [open]);

  // Debounced, abortable fetch. Code-shaped queries fire instantly; everything else
  // waits 150 ms and needs ≥2 chars (Meilisearch answers in a few ms, so a short debounce
  // still coalesces fast typing while feeling instant).
  useEffect(() => {
    if (!open) return;
    setActive(-1); // new query → drop the highlight (Enter falls back to the top hit)
    const s = q.trim();
    const code = looksLikeCode(s);
    if (s.length < 2 && !code) {
      setItems([]);
      setLoading(false);
      setError(false);
      return;
    }
    setLoading(true);
    setError(false);
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
            setError(true);
          }
        });
    }, code ? 0 : 150);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, city, open]);

  if (!open) return null;
  const s = q.trim();
  const showEmpty = !loading && !error && s.length >= 2 && items.length === 0;
  const showZero = !loading && !error && s.length < 2 && !looksLikeCode(s); // blank input → suggestions, not void
  const choose = (x: EventItem) => {
    pushRecent(q); // remember the query that led to a real tap (per-device)
    onSelect(x);
    onClose();
  };

  return (
    <div className="searchov" role="dialog" aria-modal="true" aria-label="Поиск" ref={overlayRef} tabIndex={-1}>
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
            role="combobox"
            aria-expanded={items.length > 0}
            aria-controls="searchov-results"
            aria-autocomplete="list"
            aria-activedescendant={active >= 0 ? `searchov-opt-${active}` : undefined}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                onClose();
                return;
              }
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                const hit = items[active >= 0 ? active : 0];
                if (hit) choose(hit);
              }
            }}
          />
          <button
            type="button"
            className="search__clear"
            aria-label={q ? "Очистить" : "Закрыть"}
            onClick={() => {
              if (q) {
                setQ("");
                inputRef.current?.focus();
              } else {
                onClose();
              }
            }}
          >
            <IconClose size={16} />
          </button>
        </div>

        {(items.length > 0 || showEmpty || error) && (
          <div className="searchov__results" id="searchov-results" role="listbox">
            {items.map((it, i) => (
              <EventRow
                key={it.event_id}
                item={it}
                index={i}
                query={s}
                userPos={userPos}
                active={i === active}
                optionId={`searchov-opt-${i}`}
                onSelect={choose}
              />
            ))}
            {showEmpty && <div className="searchov__empty">Ничего не найдено</div>}
            {error && <div className="searchov__empty">Не удалось загрузить. Попробуй ещё раз.</div>}
          </div>
        )}

        {showZero && (
          <div className="searchov__zero">
            {recent.length > 0 && (
              <div className="searchov__zsec">
                <div className="searchov__zhead">Недавнее</div>
                <div className="searchov__chips">
                  {recent.map((r) => (
                    <button type="button" key={r} className="searchov__chip" onClick={() => setQ(r)}>{r}</button>
                  ))}
                </div>
              </div>
            )}
            <div className="searchov__zsec">
              <div className="searchov__zhead">Попробуй</div>
              <div className="searchov__chips">
                {SUGGESTIONS.map((r) => (
                  <button type="button" key={r} className="searchov__chip" onClick={() => setQ(r)}>{r}</button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

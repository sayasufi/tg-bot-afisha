import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { CATEGORIES, categoryMeta } from "../../lib/categories";
import { PRESETS, matchPreset, nextDays, rangeFor, summarizeDate, type PresetKey } from "../../lib/datePresets";
import { CategoryIcon, IconClose, IconGrid, IconMenu, IconSearch } from "../../lib/icons";
import { clearHistory, pushHistory, readHistory } from "../../lib/searchHistory";
import { haptic, hapticSelection } from "../../lib/telegram";
import { useCountUp } from "../../lib/useCountUp";

// Free / cheap price shortcuts (₽). Empty string = no cap.
const PRICE_CHIPS: { label: string; value: string }[] = [
  { label: "Бесплатно", value: "0" },
  { label: "До 500 ₽", value: "500" },
];

export type FilterState = {
  q: string;
  category: string;
  dateFrom: string;
  dateTo: string;
  priceMax: string;
};

type Props = {
  value: FilterState;
  total: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (value: FilterState) => void;
  onMenu: () => void;
};

export function Filters({ value, total, open, onOpenChange, onChange, onMenu }: Props) {
  const [showCustomDates, setShowCustomDates] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);

  const advancedCount = [value.q, value.category, value.dateFrom || value.dateTo, value.priceMax].filter(Boolean).length;
  const shownTotal = useCountUp(total);
  const activePreset = matchPreset(value.dateFrom, value.dateTo);
  const isCustomDates = (!!value.dateFrom || !!value.dateTo) && activePreset === null;
  const catLabel = value.category ? categoryMeta(value.category).label : "Все";
  const dateLabel = summarizeDate(value.dateFrom, value.dateTo);

  // Reveal native date inputs when a custom range is already set.
  useEffect(() => {
    if (isCustomDates) setShowCustomDates(true);
  }, [isCustomDates]);

  // Refresh the recent-search list each time the sheet opens.
  useEffect(() => {
    if (open) setHistory(readHistory());
  }, [open]);

  const commitSearch = () => {
    if (value.q.trim()) {
      pushHistory(value.q);
      setHistory(readHistory());
    }
  };
  const openSheet = (focusSearch = false) => {
    haptic("light");
    onOpenChange(true);
    if (focusSearch) setTimeout(() => searchRef.current?.focus(), 320);
  };
  const close = () => {
    commitSearch();
    onOpenChange(false);
  };
  const wipeHistory = () => {
    clearHistory();
    setHistory([]);
  };
  const pick = (category: string) => {
    hapticSelection();
    onChange({ ...value, category });
  };
  const tapPreset = (key: PresetKey) => {
    hapticSelection();
    const next = activePreset === key ? { dateFrom: "", dateTo: "" } : rangeFor(key);
    setShowCustomDates(false);
    onChange({ ...value, ...next });
  };
  const days = useMemo(() => nextDays(14), []);
  const activeDay = value.dateFrom && value.dateFrom === value.dateTo ? value.dateFrom : null;
  const tapDay = (iso: string) => {
    hapticSelection();
    setShowCustomDates(false);
    onChange(activeDay === iso ? { ...value, dateFrom: "", dateTo: "" } : { ...value, dateFrom: iso, dateTo: iso });
  };

  return (
    <>
      {/* Floating command pill — the only chrome over the map at rest. */}
      <div className={`cmdpill${open ? " cmdpill--open" : ""}`}>
        <button type="button" className="cmdpill__menu" aria-label="Меню" onClick={(e) => { e.stopPropagation(); onMenu(); }}>
          <IconMenu className="cmdpill__burger" size={18} />
          <span className="cmdpill__mark">
            <span className="brand-o">о</span>крест
          </span>
        </button>
        <button type="button" className="cmdpill__body" aria-label="Фильтры" onClick={() => openSheet(false)}>
          <span className="cmdpill__summary">
            {catLabel} · {dateLabel}
          </span>
          {advancedCount > 0 && <span className="cmdpill__badge">{advancedCount}</span>}
        </button>
        <button type="button" className="cmdpill__search" aria-label="Поиск" onClick={() => openSheet(true)}>
          <IconSearch size={18} />
        </button>
      </div>

      {/* Unified filter sheet — bottom-anchored. */}
      <div className={`csheet${open ? " csheet--open" : ""}`} aria-hidden={!open}>
        <button type="button" className="csheet__scrim" aria-label="Закрыть" tabIndex={-1} onClick={close} />
        <div className="csheet__panel" role="dialog" aria-modal="true">
          <span className="csheet__grip" />
          <div className="csheet__head">
            <span className="kicker">Фильтр</span>
            <button type="button" className="icon-btn" aria-label="Закрыть" onClick={close}>
              <IconClose size={18} />
            </button>
          </div>

          <div className="search">
            <IconSearch className="search__glyph" size={18} />
            <input
              ref={searchRef}
              className="search__input"
              placeholder="Поиск событий"
              value={value.q}
              onChange={(e) => onChange({ ...value, q: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  commitSearch();
                  searchRef.current?.blur();
                }
              }}
            />
            {value.q && (
              <button type="button" className="search__clear" aria-label="Очистить" onClick={() => onChange({ ...value, q: "" })}>
                <IconClose size={15} />
              </button>
            )}
          </div>

          {!value.q && history.length > 0 && (
            <div className="histrow">
              {history.map((h) => (
                <button
                  key={h}
                  type="button"
                  className="chip chip--hist"
                  onClick={() => {
                    hapticSelection();
                    onChange({ ...value, q: h });
                  }}
                >
                  <IconSearch size={12} />
                  {h}
                </button>
              ))}
              <button type="button" className="histrow__clear" aria-label="Очистить историю" onClick={wipeHistory}>
                <IconClose size={13} />
              </button>
            </div>
          )}

          <span className="kicker">Когда</span>
          <div className="chips csheet__presets">
            {PRESETS.map((p) => (
              <button key={p.key} type="button" className={`chip${activePreset === p.key ? " chip--active" : ""}`} onClick={() => tapPreset(p.key)}>
                {p.label}
              </button>
            ))}
            <button
              type="button"
              className={`chip${showCustomDates || isCustomDates ? " chip--active" : ""}`}
              onClick={() => setShowCustomDates((v) => !v)}
            >
              Даты…
            </button>
          </div>

          {/* Day-strip — pick a single day fast without the native picker. */}
          <div className="daystrip">
            {days.map((d) => (
              <button
                key={d.iso}
                type="button"
                className={`daycell${activeDay === d.iso ? " daycell--active" : ""}${d.today ? " daycell--today" : ""}`}
                onClick={() => tapDay(d.iso)}
              >
                <span className="daycell__dow">{d.today ? "сег" : d.tomorrow ? "зав" : d.dow}</span>
                <span className="daycell__num">{d.day}</span>
              </button>
            ))}
          </div>
          {(showCustomDates || isCustomDates) && (
            <div className="csheet__dates">
              <label className="panel__field">
                <span>С даты</span>
                <input type="date" value={value.dateFrom} onChange={(e) => onChange({ ...value, dateFrom: e.target.value })} />
              </label>
              <label className="panel__field">
                <span>По дату</span>
                <input type="date" value={value.dateTo} onChange={(e) => onChange({ ...value, dateTo: e.target.value })} />
              </label>
            </div>
          )}

          <span className="kicker">Категория</span>
          <div className="csheet__grid">
            <button type="button" className={`csheet__cat${value.category === "" ? " csheet__cat--active" : ""}`} onClick={() => pick("")}>
              <IconGrid className="csheet__cat-all" size={18} />
              Все
            </button>
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                type="button"
                className={`csheet__cat${value.category === c.key ? " csheet__cat--active" : ""}`}
                style={{ "--cat": c.color } as CSSProperties}
                onClick={() => pick(c.key)}
              >
                <CategoryIcon cat={c.key} size={17} />
                {c.label}
              </button>
            ))}
          </div>

          <span className="kicker">Цена до, ₽</span>
          <div className="chips">
            {PRICE_CHIPS.map((p) => (
              <button
                key={p.value}
                type="button"
                className={`chip${value.priceMax === p.value ? " chip--active" : ""}`}
                onClick={() => {
                  hapticSelection();
                  onChange({ ...value, priceMax: value.priceMax === p.value ? "" : p.value });
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <label className="panel__field panel__field--solo">
            <input
              type="number"
              inputMode="numeric"
              placeholder="любая"
              value={value.priceMax}
              onChange={(e) => onChange({ ...value, priceMax: e.target.value })}
            />
          </label>

          <div className="csheet__foot">
            <button
              type="button"
              className="csheet__reset"
              onClick={() => {
                onChange({ q: "", category: "", dateFrom: "", dateTo: "", priceMax: "" });
                setShowCustomDates(false);
              }}
            >
              Сбросить
            </button>
            <button type="button" className="csheet__apply" onClick={close}>
              Показать {shownTotal}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

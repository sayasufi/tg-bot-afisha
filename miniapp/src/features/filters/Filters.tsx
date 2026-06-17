import { useMemo, type CSSProperties } from "react";

import { CATEGORIES, categoryMeta, categoryOrder } from "../../lib/categories";
import { PRESETS, matchPreset, nextDays, rangeFor, summarizeDate, type PresetKey } from "../../lib/datePresets";
import { CategoryIcon, IconClose, IconGrid, IconMenu, IconSearch } from "../../lib/icons";
import { haptic, hapticSelection } from "../../lib/telegram";
import { useCountUp } from "../../lib/useCountUp";

export type FilterState = {
  q: string;
  categories: string[];
  dateFrom: string;
  dateTo: string;
  priceMax: string;
  radiusKm: number; // 0 = no distance limit
  goNow: boolean; // "можно пойти сейчас" — only events you can still get to
};

export const EMPTY_FILTERS: FilterState = { q: "", categories: [], dateFrom: "", dateTo: "", priceMax: "", radiusKm: 0, goNow: false };

type Props = {
  value: FilterState;
  total: number;
  open: boolean;
  hasLocation: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (value: FilterState) => void;
  onMenu: () => void;
  onOpenSearch: () => void;
};

export function Filters({ value, total, open, hasLocation, onOpenChange, onChange, onMenu, onOpenSearch }: Props) {

  const advancedCount = [value.q, value.categories.length > 0, value.dateFrom || value.dateTo, value.priceMax, value.radiusKm > 0, value.goNow].filter(Boolean).length;
  const toggleGoNow = () => {
    hapticSelection();
    onChange({ ...value, goNow: !value.goNow });
  };
  const shownTotal = useCountUp(total);
  const activePreset = matchPreset(value.dateFrom, value.dateTo);
  const catLabel =
    value.categories.length === 0 ? "Все" : value.categories.length === 1 ? categoryMeta(value.categories[0]).label : `${value.categories.length} катег.`;
  const dateLabel = summarizeDate(value.dateFrom, value.dateTo);

  // Active filters as dismissible chips — see everything that's narrowing the list
  // at a glance, and clear any one in a single tap.
  const activeChips: { key: string; label: string; clear: () => void }[] = [];
  if (value.q.trim()) activeChips.push({ key: "q", label: `«${value.q.trim()}»`, clear: () => onChange({ ...value, q: "" }) });
  if (value.dateFrom || value.dateTo)
    activeChips.push({ key: "date", label: summarizeDate(value.dateFrom, value.dateTo), clear: () => onChange({ ...value, dateFrom: "", dateTo: "" }) });
  // Canonical order (matching the category grid), so the chip row stays put as you
  // toggle categories instead of reshuffling by the order you happened to tap them.
  for (const c of [...value.categories].sort((a, b) => categoryOrder(a) - categoryOrder(b)))
    activeChips.push({ key: `c:${c}`, label: categoryMeta(c).label, clear: () => onChange({ ...value, categories: value.categories.filter((x) => x !== c) }) });
  if (value.priceMax) activeChips.push({ key: "price", label: Number(value.priceMax) <= 0 ? "Бесплатно" : `до ${value.priceMax} ₽`, clear: () => onChange({ ...value, priceMax: "" }) });
  if (value.radiusKm > 0)
    activeChips.push({ key: "radius", label: `до ${String(value.radiusKm).replace(".", ",")} км`, clear: () => onChange({ ...value, radiusKm: 0 }) });
  if (value.goNow) activeChips.push({ key: "gonow", label: "сейчас", clear: () => onChange({ ...value, goNow: false }) });

  const openSheet = () => {
    haptic("light");
    onOpenChange(true);
  };
  const close = () => onOpenChange(false);
  // "" = all (clear). Any category toggles its membership in the multi-select.
  const pick = (category: string) => {
    hapticSelection();
    if (category === "") {
      onChange({ ...value, categories: [] });
      return;
    }
    const has = value.categories.includes(category);
    const categories = has ? value.categories.filter((c) => c !== category) : [...value.categories, category];
    onChange({ ...value, categories });
  };
  const tapPreset = (key: PresetKey) => {
    hapticSelection();
    const next = activePreset === key ? { dateFrom: "", dateTo: "" } : rangeFor(key);
    onChange({ ...value, ...next });
  };
  const days = useMemo(() => nextDays(14), []);
  const activeDay = value.dateFrom && value.dateFrom === value.dateTo ? value.dateFrom : null;
  const tapDay = (iso: string) => {
    hapticSelection();
    onChange(activeDay === iso ? { ...value, dateFrom: "", dateTo: "" } : { ...value, dateFrom: iso, dateTo: iso });
  };

  return (
    <>
      {/* Floating command pill — the only chrome over the map at rest. When the
          "Сейчас" filter is on, the whole pill pulses cinnabar so it's unmistakable
          the map is narrowed to catchable-now events. */}
      <div className={`cmdpill${open ? " cmdpill--open" : ""}${value.goNow ? " cmdpill--live" : ""}`}>
        <button type="button" className="cmdpill__menu" aria-label="Меню" onClick={(e) => { e.stopPropagation(); onMenu(); }}>
          <IconMenu className="cmdpill__burger" size={18} />
          <span className="cmdpill__mark">
            <span className="brand-o">о</span>крест
          </span>
        </button>
        <button type="button" className="cmdpill__body" aria-label="Фильтры" onClick={openSheet}>
          <span className="cmdpill__summary">
            {catLabel} · {dateLabel}
          </span>
          {advancedCount > 0 && <span className="cmdpill__badge">{advancedCount}</span>}
        </button>
        <button type="button" className="cmdpill__search" aria-label="Поиск" onClick={onOpenSearch}>
          <IconSearch size={18} />
        </button>
      </div>

      {/* Unified filter sheet — bottom-anchored. */}
      <div className={`csheet${open ? " csheet--open" : ""}`} aria-hidden={!open}>
        <button type="button" className="csheet__scrim" aria-label="Закрыть" tabIndex={-1} onClick={close} />
        <div className="csheet__panel" role="dialog" aria-modal="true">
          <span className="csheet__grip" />
          <div className="csheet__head">
            <button type="button" className="icon-btn" aria-label="Закрыть" onClick={close}>
              <IconClose size={18} />
            </button>
          </div>

          {activeChips.length > 0 && (
            <div className="csheet__active">
              {activeChips.map((ch) => (
                <button
                  key={ch.key}
                  type="button"
                  className="activechip"
                  aria-label={`Убрать фильтр: ${ch.label}`}
                  onClick={() => {
                    hapticSelection();
                    ch.clear();
                  }}
                >
                  <span>{ch.label}</span>
                  <IconClose size={12} />
                </button>
              ))}
            </div>
          )}

          {/* "Можно успеть" is a STATE filter (catch it right now), not a date range —
             so it gets its own row, away from the date presets below. */}
          <span className="kicker">Можно успеть</span>
          <button
            type="button"
            className={`gonow-toggle${value.goNow ? " gonow-toggle--on" : ""}`}
            aria-pressed={value.goNow}
            onClick={toggleGoNow}
          >
            <span className="chip__livedot" aria-hidden="true" />
            <span className="gonow-toggle__label">Сейчас</span>
            <span className="gonow-toggle__hint">идёт или открыто прямо сейчас</span>
          </button>

          <span className="kicker">Когда</span>
          <div className="chips csheet__presets">
            {PRESETS.map((p) => (
              <button key={p.key} type="button" className={`chip${activePreset === p.key ? " chip--active" : ""}`} onClick={() => tapPreset(p.key)}>
                {p.label}
              </button>
            ))}
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
                <span className="daycell__mon">{d.monLabel}</span>
                <span className="daycell__dow">{d.dow}</span>
                <span className="daycell__num">{d.day}</span>
              </button>
            ))}
          </div>
          <span className="kicker">Категория</span>
          <div className="csheet__grid">
            <button type="button" className={`csheet__cat${value.categories.length === 0 ? " csheet__cat--active" : ""}`} onClick={() => pick("")}>
              <IconGrid className="csheet__cat-all" size={18} />
              Все
            </button>
            {CATEGORIES.map((c) => (
              <button
                key={c.key}
                type="button"
                className={`csheet__cat${value.categories.includes(c.key) ? " csheet__cat--active" : ""}`}
                style={{ "--cat": c.color } as CSSProperties}
                onClick={() => pick(c.key)}
              >
                <CategoryIcon cat={c.key} size={17} />
                {c.label}
              </button>
            ))}
          </div>

          <span className="kicker">Цена до, ₽</span>
          <label className="panel__field panel__field--solo">
            <input
              type="number"
              inputMode="numeric"
              placeholder="любая"
              value={value.priceMax}
              onChange={(e) => onChange({ ...value, priceMax: e.target.value })}
            />
          </label>

          <div className="csheet__radius-head">
            <span className="kicker">Рядом</span>
            <span className="csheet__radius-val">{value.radiusKm > 0 ? `до ${String(value.radiusKm).replace(".", ",")} км` : "без ограничений"}</span>
          </div>
          {hasLocation ? (
            <input
              type="range"
              className="radius"
              min={0}
              max={10}
              step={0.5}
              value={value.radiusKm}
              onChange={(e) => onChange({ ...value, radiusKm: Number(e.target.value) })}
            />
          ) : (
            <p className="csheet__radius-hint">Включи геолокацию на карте, чтобы фильтровать по расстоянию.</p>
          )}

          <div className="csheet__foot">
            <button
              type="button"
              className="csheet__reset"
              onClick={() => onChange({ ...EMPTY_FILTERS })}
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

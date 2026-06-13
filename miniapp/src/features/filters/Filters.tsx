import { useState, type CSSProperties } from "react";

import { CATEGORIES } from "../../lib/categories";
import { hapticSelection } from "../../lib/telegram";

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
  onChange: (value: FilterState) => void;
};

export function Filters({ value, total, onChange }: Props) {
  const [showPanel, setShowPanel] = useState(false);
  const advancedCount = [value.dateFrom, value.dateTo, value.priceMax].filter(Boolean).length;

  const pick = (category: string) => {
    hapticSelection();
    onChange({ ...value, category });
  };

  return (
    <div className="topbar">
      <div className="topbar__row">
        <div className="brand">
          <span className="brand__mark">афиша</span>
          <span className="brand__count">{total} событий</span>
        </div>
        <button
          type="button"
          className={`icon-btn${advancedCount ? " icon-btn--active" : ""}`}
          aria-label="Фильтры"
          onClick={() => setShowPanel((v) => !v)}
        >
          <span className="icon-btn__glyph">⚙</span>
          {advancedCount > 0 && <span className="icon-btn__badge">{advancedCount}</span>}
        </button>
      </div>

      <div className="search">
        <span className="search__glyph">🔍</span>
        <input
          className="search__input"
          placeholder="Поиск событий"
          value={value.q}
          onChange={(e) => onChange({ ...value, q: e.target.value })}
        />
        {value.q && (
          <button type="button" className="search__clear" aria-label="Очистить" onClick={() => onChange({ ...value, q: "" })}>
            ✕
          </button>
        )}
      </div>

      <div className="chips">
        <button type="button" className={`chip${value.category === "" ? " chip--active" : ""}`} onClick={() => pick("")}>
          Все
        </button>
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            type="button"
            className={`chip${value.category === c.key ? " chip--active" : ""}`}
            style={{ "--c": c.color } as CSSProperties}
            onClick={() => pick(c.key)}
          >
            <span className="chip__glyph">{c.glyph}</span>
            {c.label}
          </button>
        ))}
      </div>

      {showPanel && (
        <div className="panel">
          <label className="panel__field">
            <span>С даты</span>
            <input type="date" value={value.dateFrom} onChange={(e) => onChange({ ...value, dateFrom: e.target.value })} />
          </label>
          <label className="panel__field">
            <span>По дату</span>
            <input type="date" value={value.dateTo} onChange={(e) => onChange({ ...value, dateTo: e.target.value })} />
          </label>
          <label className="panel__field">
            <span>Цена до, ₽</span>
            <input
              type="number"
              inputMode="numeric"
              placeholder="любая"
              value={value.priceMax}
              onChange={(e) => onChange({ ...value, priceMax: e.target.value })}
            />
          </label>
          <button
            type="button"
            className="panel__reset"
            onClick={() => onChange({ ...value, dateFrom: "", dateTo: "", priceMax: "" })}
          >
            Сбросить
          </button>
        </div>
      )}
    </div>
  );
}

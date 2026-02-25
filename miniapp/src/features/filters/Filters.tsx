import { useMemo } from "react";

type FilterState = {
  q: string;
  category: string;
  dateFrom: string;
  dateTo: string;
  priceMax: string;
};

type Props = {
  value: FilterState;
  onChange: (value: FilterState) => void;
};

const categories = ["", "concert", "theatre", "exhibition", "standup", "festival", "other"];

export function Filters({ value, onChange }: Props) {
  const cats = useMemo(() => categories, []);

  return (
    <div className="toolbar">
      <input
        placeholder="Поиск"
        value={value.q}
        onChange={(e) => onChange({ ...value, q: e.target.value })}
      />
      <select value={value.category} onChange={(e) => onChange({ ...value, category: e.target.value })}>
        {cats.map((c) => (
          <option key={c} value={c}>
            {c || "all categories"}
          </option>
        ))}
      </select>
      <input type="date" value={value.dateFrom} onChange={(e) => onChange({ ...value, dateFrom: e.target.value })} />
      <input type="date" value={value.dateTo} onChange={(e) => onChange({ ...value, dateTo: e.target.value })} />
      <input
        type="number"
        placeholder="max price"
        value={value.priceMax}
        onChange={(e) => onChange({ ...value, priceMax: e.target.value })}
      />
    </div>
  );
}

import { ReactNode, useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export type SortState = { key: string; dir: SortDir };

function cmp(a: any, b: any): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1; // null/undefined всегда в конце
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return a === b ? 0 : a ? -1 : 1;
  return String(a).localeCompare(String(b), "ru");
}

/** Клиентская сортировка загруженной страницы. get(item, key) → значение колонки key. */
export function useSort<T>(items: T[], get: (x: T, key: string) => any, initial: SortState) {
  const [sort, setSort] = useState<SortState>(initial);
  const sorted = useMemo(() => {
    const arr = [...items].sort((a, b) => cmp(get(a, sort.key), get(b, sort.key)));
    return sort.dir === "desc" ? arr.reverse() : arr;
    // get стабилен по смыслу — не включаем в зависимости
  }, [items, sort.key, sort.dir]);
  const onSort = (key: string) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  return { sorted, sort, onSort };
}

export function SortTh({
  label,
  k,
  sort,
  onSort,
  className,
}: {
  label: ReactNode;
  k: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = sort.key === k;
  return (
    <th
      className={"sort-th" + (active ? " sort-th--active" : "") + (className ? " " + className : "")}
      onClick={() => onSort(k)}
    >
      {label}
      <span className="sort-th__arr">{active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}</span>
    </th>
  );
}

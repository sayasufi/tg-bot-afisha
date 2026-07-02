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
    // Направление внутри компаратора: NULL всегда в конце (не переворачиваем массив
    // целиком, иначе при desc null уезжает в НАЧАЛО). null-ветки cmp не инвертируем.
    const dir = sort.dir === "desc" ? -1 : 1;
    return [...items].sort((a, b) => {
      const va = get(a, sort.key), vb = get(b, sort.key);
      if (va == null || vb == null) return cmp(va, vb); // null-порядок инвариантен к dir
      return dir * cmp(va, vb);
    });
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

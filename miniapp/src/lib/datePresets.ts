// Quick date presets for the filter sheet. All values are LOCAL yyyy-mm-dd so
// App's `new Date(filters.dateFrom).toISOString()` keeps working unchanged.

export type PresetKey = "today" | "tomorrow" | "weekend" | "week" | "month";

export const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "today", label: "Сегодня" },
  { key: "tomorrow", label: "Завтра" },
  { key: "weekend", label: "Выходные" },
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
];

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (base: Date, n: number) => {
  const d = new Date(base);
  d.setDate(d.getDate() + n);
  return d;
};

export function rangeFor(key: PresetKey, now: Date = new Date()): { dateFrom: string; dateTo: string } {
  const t = new Date(now.getFullYear(), now.getMonth(), now.getDate()); // local midnight
  switch (key) {
    case "today":
      return { dateFrom: iso(t), dateTo: iso(t) };
    case "tomorrow": {
      const x = addDays(t, 1);
      return { dateFrom: iso(x), dateTo: iso(x) };
    }
    case "weekend": {
      const dow = t.getDay(); // 0=Sun..6=Sat
      let sat: Date, sun: Date;
      if (dow === 0) {
        sat = addDays(t, -1);
        sun = t;
      } else if (dow === 6) {
        sat = t;
        sun = addDays(t, 1);
      } else {
        sat = addDays(t, 6 - dow);
        sun = addDays(t, 7 - dow);
      }
      return { dateFrom: iso(sat), dateTo: iso(sun) };
    }
    case "week":
      return { dateFrom: iso(t), dateTo: iso(addDays(t, 6)) };
    case "month":
      return { dateFrom: iso(t), dateTo: iso(addDays(t, 29)) };
  }
}

export function matchPreset(dateFrom: string, dateTo: string, now: Date = new Date()): PresetKey | null {
  if (!dateFrom && !dateTo) return null;
  for (const { key } of PRESETS) {
    const r = rangeFor(key, now);
    if (r.dateFrom === dateFrom && r.dateTo === dateTo) return key;
  }
  return null; // dates set, but a custom range
}

const RU_MON = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

// Compact pill summary token, e.g. "СЕГОДНЯ" / "12–18 ИЮН" / "ВСЕ ДАТЫ".
export function summarizeDate(dateFrom: string, dateTo: string, now: Date = new Date()): string {
  const p = matchPreset(dateFrom, dateTo, now);
  if (p) return PRESETS.find((x) => x.key === p)!.label.toUpperCase();
  if (!dateFrom && !dateTo) return "ВСЕ ДАТЫ";
  const fmt = (s: string) => {
    const [, m, d] = s.split("-");
    return `${Number(d)} ${RU_MON[Number(m) - 1]}`;
  };
  if (dateFrom && dateTo && dateFrom !== dateTo) return `${fmt(dateFrom)}–${fmt(dateTo)}`.toUpperCase();
  return fmt(dateFrom || dateTo).toUpperCase();
}

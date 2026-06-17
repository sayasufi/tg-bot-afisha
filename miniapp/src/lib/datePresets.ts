// Quick date presets for the filter sheet. Values are Moscow-anchored yyyy-mm-dd:
// "Сегодня" means today-in-Moscow for every client, regardless of device timezone
// (the events are Moscow wall-clock times). App pairs these with +03:00 ISO bounds.

export type PresetKey = "today" | "tomorrow" | "weekend" | "week" | "month";

export const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "today", label: "Сегодня" },
  { key: "tomorrow", label: "Завтра" },
  { key: "weekend", label: "Выходные" },
  { key: "week", label: "Неделя" },
];

// All current cities are UTC+3 (Europe/Moscow, no DST since 2014). "Now" in Moscow,
// returned as a Date whose LOCAL y/m/d are Moscow's calendar day — every consumer
// only reads getFullYear/Month/Date/getDay off it, never the absolute instant. So
// the day-strip and presets stay on the Moscow calendar even for a non-MSK device.
const APP_TZ = "Europe/Moscow";
function mskToday(now: Date = new Date()): Date {
  const [y, m, d] = new Intl.DateTimeFormat("en-CA", {
    timeZone: APP_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(now)
    .split("-")
    .map(Number);
  return new Date(y, m - 1, d);
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (base: Date, n: number) => {
  const d = new Date(base);
  d.setDate(d.getDate() + n);
  return d;
};

export function rangeFor(key: PresetKey, now: Date = new Date()): { dateFrom: string; dateTo: string } {
  const t = mskToday(now); // Moscow's today (not the device's)
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

const RU_DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const RU_MON = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

export type DayCell = { iso: string; dow: string; day: number; today: boolean; tomorrow: boolean; monLabel: string };

// The next `count` days as cells for the day-strip selector. The first two are
// flagged so the UI can label them "Сегодня" / "Завтра". `monLabel` carries the
// (uppercase) month on the first cell and whenever the strip crosses into a new
// month, so a number near the month boundary isn't ambiguous; "" otherwise.
export function nextDays(count = 14, now: Date = new Date()): DayCell[] {
  const t = mskToday(now);
  let prevMonth = -1;
  return Array.from({ length: count }, (_, i) => {
    const d = addDays(t, i);
    const m = d.getMonth();
    const monLabel = i === 0 || m !== prevMonth ? RU_MON[m].toUpperCase() : "";
    prevMonth = m;
    return { iso: iso(d), dow: RU_DOW[d.getDay()], day: d.getDate(), today: i === 0, tomorrow: i === 1, monLabel };
  });
}

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

// Unified event date/time formatting. Sources give messy ranges: point events
// (often with date_end == date_start), same-day time ranges, short multi-day
// festivals, long exhibition runs (months), and "open-ended" rows whose end is
// a far-future sentinel (e.g. 9998-12-31) meaning a permanent/ongoing event.
// These helpers collapse all of that into one sensible Russian format.

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function parse(iso?: string | null): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}
const isMidnight = (d: Date) => d.getHours() === 0 && d.getMinutes() === 0;
const pad = (n: number) => String(n).padStart(2, "0");
const hm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const dayDiff = (a: Date, b: Date) => {
  const A = new Date(a.getFullYear(), a.getMonth(), a.getDate()).getTime();
  const B = new Date(b.getFullYear(), b.getMonth(), b.getDate()).getTime();
  return Math.round((B - A) / 86400000);
};
const dmy = (d: Date, withYear: boolean, short = false) =>
  `${d.getDate()} ${(short ? MONTHS_SHORT : MONTHS)[d.getMonth()]}${withYear ? ` ${d.getFullYear()}` : ""}`;

// Classify the end: a real end, nothing, or an open-ended sentinel (>5y out).
function endInfo(s: Date, endIso: string | null | undefined, now: Date): { end: Date | null; open: boolean } {
  const e = parse(endIso);
  if (!e) return { end: null, open: false };
  if (e.getFullYear() > now.getFullYear() + 5) return { end: null, open: true }; // 9998-style sentinel
  if (e.getTime() <= s.getTime()) return { end: null, open: false }; // missing/redundant
  return { end: e, open: false };
}

// Full format for the detail sheet, e.g.:
//   "19 июня, 18:30"        "19 июня, 18:30–22:00"        "по 1 января"
//   "постоянно"             "с 9 августа"                 "19 июня — 21 июня"
export function formatWhen(startIso?: string | null, endIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  const { end: e, open } = endInfo(s, endIso, now);
  const yr = (d: Date) => d.getFullYear() !== now.getFullYear();
  const hasTime = !isMidnight(s);

  if (open) {
    if (s.getTime() <= now.getTime()) return "постоянно";
    return `с ${dmy(s, yr(s))}` + (hasTime ? `, ${hm(s)}` : "");
  }
  if (!e) return dmy(s, yr(s)) + (hasTime ? `, ${hm(s)}` : "");

  if (sameDay(s, e)) {
    if (!hasTime) return dmy(s, yr(s));
    return dmy(s, yr(s)) + `, ${hm(s)}` + (!isMidnight(e) ? `–${hm(e)}` : "");
  }
  if (dayDiff(s, e) <= 2) {
    const sp = dmy(s, yr(s)) + (hasTime ? `, ${hm(s)}` : "");
    const ep = dmy(e, yr(e)) + (!isMidnight(e) ? `, ${hm(e)}` : "");
    return `${sp} — ${ep}`;
  }
  if (s.getTime() <= now.getTime()) return `по ${dmy(e, yr(e))}`;
  return `${dmy(s, yr(s))} — ${dmy(e, yr(e))}`;
}

// Compact format for list rows / ticker (short months).
export function formatWhenShort(startIso?: string | null, endIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  const { end: e, open } = endInfo(s, endIso, now);
  const yr = (d: Date) => d.getFullYear() !== now.getFullYear();
  const hasTime = !isMidnight(s);

  if (open) {
    if (s.getTime() <= now.getTime()) return "постоянно";
    return `с ${dmy(s, false, true)}`;
  }
  if (e && !sameDay(s, e)) {
    if (dayDiff(s, e) > 2 && s.getTime() <= now.getTime()) return `по ${dmy(e, yr(e), true)}`;
    return `${dmy(s, false, true)} — ${dmy(e, yr(e), true)}`;
  }
  if (e && sameDay(s, e) && hasTime) {
    return dmy(s, yr(s), true) + `, ${hm(s)}` + (!isMidnight(e) ? `–${hm(e)}` : "");
  }
  return dmy(s, yr(s), true) + (hasTime ? `, ${hm(s)}` : "");
}

// Time bucket for grouping a listing: separates one-off upcoming events from
// long-running exhibitions ("идут сейчас") and permanent ones ("постоянно").
export type Bucket = { key: string; label: string; order: number };

export function eventBucket(startIso?: string | null, endIso?: string | null, now: Date = new Date()): Bucket {
  const s = parse(startIso);
  if (!s) return { key: "later", label: "Позже", order: 3 };
  const { end: e, open } = endInfo(s, endIso, now);
  if (open) return { key: "perm", label: "Постоянно", order: 5 };
  if (e && dayDiff(s, e) > 3 && s.getTime() <= now.getTime()) {
    return { key: "ongoing", label: "Идут сейчас", order: 4 };
  }
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const ds = dayDiff(today, s);
  if (ds <= 0) return { key: "today", label: "Сегодня", order: 1 };
  if (ds <= 7) return { key: "week", label: "На этой неделе", order: 2 };
  return { key: "later", label: "Позже", order: 3 };
}

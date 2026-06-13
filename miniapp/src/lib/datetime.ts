// Unified event date/time formatting. Sources give messy ranges: point events
// (often with date_end == date_start), same-day time ranges, short multi-day
// festivals, and long exhibition runs (months, sometimes a stray start time).
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

// Drop an end that is missing, equal to, or before the start.
function endOf(s: Date, endIso?: string | null): Date | null {
  const e = parse(endIso);
  return e && e.getTime() > s.getTime() ? e : null;
}

// Full format for the detail sheet, e.g.:
//   "19 июня, 18:30"            (point)
//   "19 июня, 18:30–22:00"      (same day)
//   "19 июня — 21 июня"         (short run, future)
//   "по 1 января"               (long run already started)
export function formatWhen(startIso?: string | null, endIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  const e = endOf(s, endIso);
  const yr = (d: Date) => d.getFullYear() !== now.getFullYear();
  const hasTime = !isMidnight(s);

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

// Compact format for list rows / ticker (short months), e.g.:
//   "19 июн, 18:30" · "19 июн, 18:30–22:00" · "по 1 янв" · "19 июн — 21 июн"
export function formatWhenShort(startIso?: string | null, endIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  const e = endOf(s, endIso);
  const yr = (d: Date) => d.getFullYear() !== now.getFullYear();
  const hasTime = !isMidnight(s);

  if (e && !sameDay(s, e)) {
    if (dayDiff(s, e) > 2) {
      if (s.getTime() <= now.getTime()) return `по ${dmy(e, yr(e), true)}`;
      return `${dmy(s, false, true)} — ${dmy(e, yr(e), true)}`;
    }
    return `${dmy(s, false, true)} — ${dmy(e, yr(e), true)}`;
  }
  if (e && sameDay(s, e) && hasTime) {
    return dmy(s, yr(s), true) + `, ${hm(s)}` + (!isMidnight(e) ? `–${hm(e)}` : "");
  }
  return dmy(s, yr(s), true) + (hasTime ? `, ${hm(s)}` : "");
}

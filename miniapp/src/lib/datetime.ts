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

// Every event datetime arrives as an absolute UTC instant (e.g. "…T16:00:00+00:00" = 19:00 MSK).
// The UI must show MOSCOW wall-clock regardless of the device's timezone, so all field reads (hour,
// day, weekday, year…) go through `_msk` — never Date.getHours()/getDate(), which render the
// VIEWER's local time. Moscow is a FIXED UTC+3 (no DST since 2014), so shifting +3h and reading the
// UTC getters is both correct and far cheaper than Intl for the thousands of live/goNow checks per
// tick. getTime() comparisons stay on the TRUE instant (timezone-independent) and are left as-is.
const MSK_OFFSET_MS = 3 * 3600 * 1000;
const _msk = (d: Date) => new Date(d.getTime() + MSK_OFFSET_MS); // read ONLY via getUTC* → MSK fields
const mskDayIdx = (d: Date) => Math.floor((d.getTime() + MSK_OFFSET_MS) / 86400000); // MSK calendar day

function parse(iso?: string | null): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}
const isMidnight = (d: Date) => {
  const m = _msk(d);
  return m.getUTCHours() === 0 && m.getUTCMinutes() === 0;
};
const pad = (n: number) => String(n).padStart(2, "0");
const hm = (d: Date) => {
  const m = _msk(d);
  return `${pad(m.getUTCHours())}:${pad(m.getUTCMinutes())}`;
};
const sameDay = (a: Date, b: Date) => mskDayIdx(a) === mskDayIdx(b);
const dayDiff = (a: Date, b: Date) => mskDayIdx(b) - mskDayIdx(a);

// The instant (ms) of the END of *today* in Moscow — for "is this on/by today?" checks that must
// use the Moscow calendar day, not the viewer's. Next MSK midnight minus 1ms.
export function mskEndOfTodayMs(now: Date = new Date()): number {
  return (mskDayIdx(now) + 1) * 86400000 - MSK_OFFSET_MS - 1;
}

// True when `iso` falls on TODAY's Moscow calendar day. Gates "today-only" UI — e.g. a date-only
// event's venue-hours line ("сегодня 12:00–24:00") only makes sense if the event is actually today;
// on a future day it would read as a misleading "сегодня".
export function isMskToday(iso?: string | null, now: Date = new Date()): boolean {
  const d = parse(iso);
  return !!d && mskDayIdx(d) === mskDayIdx(now);
}

const hmToMin = (hm: string): number => {
  const [h, m] = String(hm).split(":");
  return (Number(h) || 0) * 60 + (Number(m) || 0);
};

// All-week round-the-clock almost always means the hours scraper matched an
// always-open TERRITORY (a park, an embankment) or a 24/7 building (a hotel that
// shares the venue's name), not the event's actual hall — a real event venue is
// ~never genuinely 24/7. So we treat "every day 00:00–24:00" as UNKNOWN hours
// rather than asserting круглосуточно for the event.
function isRoundTheClockDay(day: (string[] | null)[] | null): boolean {
  if (!Array.isArray(day) || day.length !== 1) return false;
  const r = day[0];
  return Array.isArray(r) && r.length === 2 && (r[0] === r[1] || (r[0] === "00:00" && (r[1] === "24:00" || r[1] === "00:00")));
}
export function isTerritoryHours(hours: { week?: (string[][] | null)[] } | null | undefined): boolean {
  const week = hours?.week;
  return Array.isArray(week) && week.length === 7 && week.every(isRoundTheClockDay);
}

// Is the venue open at `now` per its weekly hours? true / false / null (unknown).
export function venueOpenNow(
  hours: { week?: (string[][] | null)[] } | null | undefined,
  now: Date = new Date(),
): boolean | null {
  const week = hours?.week;
  if (!Array.isArray(week) || week.length !== 7) return null;
  if (isTerritoryHours(hours)) return null; // 24/7 territory → we don't know the event's hours
  const m = _msk(now);
  const day = week[m.getUTCDay()];
  if (day === null) return false; // closed today
  if (!Array.isArray(day) || day.length === 0) return null; // unknown
  const mins = m.getUTCHours() * 60 + m.getUTCMinutes();
  for (const r of day) {
    if (!Array.isArray(r) || r.length !== 2) continue;
    const open = hmToMin(r[0]);
    const close = hmToMin(r[1]) || 1440; // 00:00 close = end of day
    if (open === close) return true; // round-the-clock
    if (mins >= open && mins < close) return true;
  }
  return false; // outside today's ranges
}

// True if you can experience the event RIGHT NOW — what the red "идёт сейчас"
// pulse promises. Either a timed session is in progress, OR it's an ongoing run
// (exhibition etc.) whose venue is open at this moment. A run with a venue
// closed today does NOT pulse; unknown hours fall back to "ongoing → live".
export function isLiveNow(start?: string | null, end?: string | null, hours?: { week?: (string[][] | null)[] } | null): boolean {
  const s = parse(start);
  if (!s) return false;
  const now = Date.now();
  if (s.getTime() > now) return false; // not started
  const e = parse(end);
  const endMs = e ? e.getTime() : s.getTime() + 3 * 3600 * 1000;
  // Timed session (real start time, ≤24h window): live while inside it.
  if (!isMidnight(s) && endMs - s.getTime() <= 24 * 3600 * 1000) {
    return now <= endMs;
  }
  // Run / all-day / ongoing: must still be within its run, and venue open now.
  const farFuture = !!e && _msk(e).getUTCFullYear() > _msk(new Date(now)).getUTCFullYear() + 5;
  if (e && !farFuture && now > e.getTime()) return false; // run already over
  return venueOpenNow(hours, new Date()) !== false; // closed now → not live
}

// ── "Можно пойти сейчас" ─────────────────────────────────────────────────────
// Whether you can REALISTICALLY still get to an event — the smart successor to
// the blunt red pulse. Two shapes, mirroring the timed/ongoing split used across
// this file:
//   • TIMED (cinema/concert/theatre — a real start time, run ≤24h): catchable
//     while it HASN'T started yet and starts within the "soon" window (3 hours).
//     A session already in progress is NEVER catchable — you can't walk into a
//     film that began (the whole point of the feature).
//   • ONGOING (museum/exhibition/permanent — midnight start or a multi-day run):
//     catchable while its run is live AND the venue is open at this very moment.
// `now` is injectable so a single tick can drive the whole UI consistently.
export const SOON_MAX_MIN = 180; // surface timed events starting within 3 hours

export type GoNow =
  | { eligible: false }
  | { eligible: true; kind: "soon"; minutesUntilStart: number; label: string }
  | { eligible: true; kind: "now"; label: string };

// "через 25 мин" / "через 1 ч 20 мин"; "вот-вот" under 2 min so a stale
// "через 1 мин" never lingers past the start between minute ticks.
function untilLabel(m: number): string {
  if (m < 2) return "вот-вот";
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h === 0) return `через ${mm} мин`;
  if (mm === 0) return `через ${h} ч`;
  return `через ${h} ч ${mm} мин`;
}

// `openNow` is a precomputed tri-state (true/false/null-unknown): the map ships it
// server-computed in Moscow time; the detail sheet derives it via venueOpenNow() from
// the full hours. Only the ONGOING branch uses it — the timed "soon" branch is purely
// date-based and stays live off `now`.
export function goNowState(
  start?: string | null,
  end?: string | null,
  openNow?: boolean | null,
  now: Date = new Date(),
): GoNow {
  const s = parse(start);
  if (!s) return { eligible: false };
  const e = parse(end);
  const endMs = e ? e.getTime() : s.getTime() + 3 * 3600 * 1000;
  const timed = !isMidnight(s) && endMs - s.getTime() <= 24 * 3600 * 1000;

  if (timed) {
    const ms = s.getTime() - now.getTime();
    if (ms <= 0) return { eligible: false }; // already started — can't catch it (exact, no rounding)
    const minutesUntilStart = Math.round(ms / 60000);
    if (minutesUntilStart > SOON_MAX_MIN) return { eligible: false }; // not soon enough
    return { eligible: true, kind: "soon", minutesUntilStart, label: untilLabel(minutesUntilStart) };
  }

  // Ongoing / all-day / permanent: must have BEGUN, still be running, venue open.
  // The "has it started?" guard is critical — without it a future all-day or
  // multi-day event (a lecture dated 28 June stored as 00:00, or a 2-day festival)
  // in a round-the-clock venue would falsely read "идёт сейчас".
  const { end: realEnd, open } = endInfo(s, end, now);
  if (s.getTime() > now.getTime()) return { eligible: false }; // hasn't started yet
  if (!open && realEnd && now.getTime() > realEnd.getTime()) return { eligible: false }; // run is over
  // Only "идёт сейчас" when we KNOW the venue is open right now (real hours). If the
  // hours are unknown ("время уточняйте"), we can't claim it's on — so it's never red.
  if (openNow !== true) return { eligible: false };
  return { eligible: true, kind: "now", label: "идёт сейчас" };
}
const dmy = (d: Date, withYear: boolean, short = false) => {
  const m = _msk(d);
  return `${m.getUTCDate()} ${(short ? MONTHS_SHORT : MONTHS)[m.getUTCMonth()]}${withYear ? ` ${m.getUTCFullYear()}` : ""}`;
};

// Classify the end: a real end, nothing, or an open-ended sentinel (>5y out).
function endInfo(s: Date, endIso: string | null | undefined, now: Date): { end: Date | null; open: boolean } {
  const e = parse(endIso);
  if (!e) return { end: null, open: false };
  if (_msk(e).getUTCFullYear() > _msk(now).getUTCFullYear() + 5) return { end: null, open: true }; // 9998-style sentinel
  if (e.getTime() <= s.getTime()) return { end: null, open: false }; // missing/redundant
  return { end: e, open: false };
}

// Full format for the detail sheet, e.g.:
//   "19 июня, 18:30"        "19 июня, 18:30–22:00"        "до 1 января"
//   "постоянно"             "с 9 августа"                 "19 июня — 21 июня"
export function formatWhen(startIso?: string | null, endIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  const { end: e, open } = endInfo(s, endIso, now);
  const nowY = _msk(now).getUTCFullYear();
  const yr = (d: Date) => _msk(d).getUTCFullYear() !== nowY;
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
  if (s.getTime() <= now.getTime()) return `до ${dmy(e, yr(e))}`;
  return `${dmy(s, yr(s))} — ${dmy(e, yr(e))}`;
}

// An honest note for events with NO clock time, so they don't read as 24/7:
//   ""               — has a real time, nothing to add
//   "в часы работы"  — an ongoing run / permanent exhibit (open during venue hours)
//   "время уточняйте" — a one-off without a known time (check before you go)
export function whenTimeNote(startIso?: string | null, _endIso?: string | null, _now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s || !isMidnight(s)) return ""; // has a real clock time → nothing to add
  // All-day / ongoing with no event time: honest "время уточняйте" by default. The
  // sheet upgrades this to the venue's real hours ("сегодня 10:00–20:00") when we
  // have them — but never to a misleading "в часы работы" / 24-7 "круглосуточно".
  return "время уточняйте";
}

// Today's opening hours from a venue's weekly schedule (index 0=Sunday):
//   "сегодня 10:00–22:00"   "сегодня закрыто"   null (unknown)
export function venueHoursToday(
  hours: { week?: (string[][] | null)[] } | null | undefined,
  now: Date = new Date(),
): string | null {
  const week = hours?.week;
  if (!Array.isArray(week) || week.length !== 7) return null;
  if (isTerritoryHours(hours)) return null; // all-week 24/7 = matched a territory, not the hall
  const day = week[_msk(now).getUTCDay()];
  if (day === null) return "сегодня закрыто";
  if (!Array.isArray(day) || day.length === 0) return null;
  // Round-the-clock for a single day (a genuine 24h spot, not an all-week territory).
  const is24 = (r: string[]) => r[0] === r[1] || (r[0] === "00:00" && (r[1] === "24:00" || r[1] === "00:00"));
  if (day.length === 1 && Array.isArray(day[0]) && is24(day[0])) return "сегодня круглосуточно";
  const ranges = day
    .filter((r) => Array.isArray(r) && r.length === 2)
    .map((r) => `${r[0]}–${r[1] === "00:00" ? "24:00" : r[1]}`)
    .join(", ");
  return ranges ? `сегодня ${ranges}` : null;
}

// One session as a compact chip for the sheet's "all dates" list: "17 июн, 19:00"
// (or just "17 июн" with no clock time). Year only when it isn't the current one.
export function formatDateChip(startIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  return dmy(s, _msk(s).getUTCFullYear() !== _msk(now).getUTCFullYear(), true) + (isMidnight(s) ? "" : `, ${hm(s)}`);
}

// Compact format for list rows / ticker (short months).
export function formatWhenShort(startIso?: string | null, endIso?: string | null, now: Date = new Date()): string {
  const s = parse(startIso);
  if (!s) return "";
  const { end: e, open } = endInfo(s, endIso, now);
  const nowY = _msk(now).getUTCFullYear();
  const yr = (d: Date) => _msk(d).getUTCFullYear() !== nowY;
  const hasTime = !isMidnight(s);

  if (open) {
    if (s.getTime() <= now.getTime()) return "постоянно";
    return `с ${dmy(s, false, true)}`;
  }
  if (e && !sameDay(s, e)) {
    if (dayDiff(s, e) > 2 && s.getTime() <= now.getTime()) return `до ${dmy(e, yr(e), true)}`;
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
  const ds = dayDiff(now, s); // whole days from today (both in Moscow calendar)
  if (ds <= 0) return { key: "today", label: "Сегодня", order: 1 };
  if (ds <= 7) return { key: "week", label: "На этой неделе", order: 2 };
  return { key: "later", label: "Позже", order: 3 };
}

// Build an .ics calendar event and hand it to the OS ("Add to calendar").

export type CalendarEvent = {
  id: string;
  title: string;
  start: string;
  end?: string | null;
  location?: string | null;
  description?: string | null;
  url?: string | null;
};

const pad = (n: number) => String(n).padStart(2, "0");

function fmt(d: Date): string {
  return (
    d.getUTCFullYear() +
    pad(d.getUTCMonth() + 1) +
    pad(d.getUTCDate()) +
    "T" +
    pad(d.getUTCHours()) +
    pad(d.getUTCMinutes()) +
    pad(d.getUTCSeconds()) +
    "Z"
  );
}

function esc(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

export function buildIcs(e: CalendarEvent): string {
  const start = e.start ? new Date(e.start) : null;
  const hasStart = !!start && !Number.isNaN(start.getTime());
  let end = e.end ? new Date(e.end) : null;
  // Open-ended / "постоянно" events use a far-future sentinel — give them a
  // sensible 2h block instead of a year-9998 calendar entry.
  if (hasStart && (!end || Number.isNaN(end.getTime()) || end.getUTCFullYear() > 2100)) {
    end = new Date(start!.getTime() + 2 * 3600 * 1000);
  }
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Окрест//RU",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${e.id}@okrest`,
    `DTSTAMP:${fmt(new Date())}`,
    hasStart ? `DTSTART:${fmt(start!)}` : "",
    end ? `DTEND:${fmt(end)}` : "",
    `SUMMARY:${esc(e.title)}`,
    e.location ? `LOCATION:${esc(e.location)}` : "",
    e.description ? `DESCRIPTION:${esc(e.description)}` : "",
    e.url ? `URL:${esc(e.url)}` : "",
    "END:VEVENT",
    "END:VCALENDAR",
  ].filter(Boolean);
  return lines.join("\r\n");
}

// Trigger the native "add to calendar" via an .ics download.
export function addToCalendar(e: CalendarEvent): void {
  const blob = new Blob([buildIcs(e)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "okrest-event.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}

// Presentation helpers for the event sheet.

// Short museum "accession" codes per category, for the catalogue affect.
export const CAT_CODE: Record<string, string> = {
  concert: "КОНЦ",
  theatre: "ТЕАТР",
  exhibition: "ВЫСТ",
  cinema: "КИНО",
  standup: "СТЕНД",
  festival: "ФЕСТ",
  lecture: "ЛЕКЦ",
  tour: "ЭКСК",
  party: "ВЕЧЕР",
  kids: "ДЕТИ",
  other: "ПРОЧ",
};

export function stripHtml(text: string): string {
  return text
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&[a-z]+;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const rub = (n: number) => `${Math.round(n)} ₽`;

export function formatPrice(min: number | null | undefined, max?: number | null): string {
  if (min == null && max == null) return "Цена не указана";
  const lo = min ?? 0;
  const hi = max ?? null;
  if (lo === 0 && (hi == null || hi === 0)) return "Бесплатно";
  if (lo === 0 && hi != null && hi > 0) return `до ${rub(hi)}`;
  if (hi != null && hi > lo) return `${Math.round(lo)}–${rub(hi)}`;
  return `от ${rub(lo)}`;
}

// Stable 4-digit "accession" sequence from the event id.
export function accessionNo(id: string | number): string {
  const s = String(id);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return String(h % 10000).padStart(4, "0");
}

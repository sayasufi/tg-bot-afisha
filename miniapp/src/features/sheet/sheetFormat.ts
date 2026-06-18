// Presentation helpers for the event sheet.

export function stripHtml(text: string): string {
  return text
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&[a-z]+;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const rub = (n: number) => `${Math.round(n)} ₽`;

// The detail API serialises Decimal as a string ("0.00"), the map as a number —
// coerce so the free/“от 0” checks work for both.
const num = (v: number | string | null | undefined): number | null => {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

export function formatPrice(min: number | string | null | undefined, max?: number | string | null): string {
  const lo = num(min);
  const hi = num(max);
  if (lo == null && hi == null) return "Цена не указана";
  const L = lo ?? 0;
  if (L === 0 && (hi == null || hi === 0)) return "Бесплатно";
  if (L === 0 && hi != null && hi > 0) return `до ${rub(hi)}`;
  if (hi != null && hi > L) return `${Math.round(L)}–${rub(hi)}`;
  return `от ${rub(L)}`;
}

// Stable 4-digit "accession" sequence from the event id.
export function accessionNo(id: string | number): string {
  const s = String(id);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return String(h % 10000).padStart(4, "0");
}

// Presentation helpers for the event sheet.

// Short museum "accession" codes per category, for the catalogue affect.
export const CAT_CODE: Record<string, string> = {
  concert: "КОНЦ",
  theatre: "ТЕАТР",
  exhibition: "ВЫСТ",
  standup: "СТЕНД",
  festival: "ФЕСТ",
  lecture: "ЛЕКЦ",
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

export function formatPrice(price: number | null | undefined): string {
  if (price == null) return "Цена не указана";
  if (price === 0) return "Бесплатно";
  return `от ${Math.round(price)} ₽`;
}

// Stable 4-digit "accession" sequence from the event id.
export function accessionNo(id: string | number): string {
  const s = String(id);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return String(h % 10000).padStart(4, "0");
}

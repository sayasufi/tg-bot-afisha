export type CategoryMeta = {
  key: string;
  label: string;
  glyph: string;
  color: string;
};

// Muted, editorial palette — distinct but never neon (no bright pink).
export const CATEGORIES: CategoryMeta[] = [
  { key: "concert", label: "Концерты", glyph: "🎵", color: "#DB6A4E" },
  { key: "theatre", label: "Театр", glyph: "🎭", color: "#C9A24A" },
  { key: "exhibition", label: "Выставки", glyph: "🖼️", color: "#9C7BD0" },
  { key: "standup", label: "Стендап", glyph: "🎤", color: "#E08A3C" },
  { key: "festival", label: "Фестивали", glyph: "🎪", color: "#4FA487" },
  { key: "lecture", label: "Лекции", glyph: "🎓", color: "#5784C2" },
  { key: "kids", label: "Детям", glyph: "🧸", color: "#5BC0B6" },
  { key: "other", label: "Другое", glyph: "✨", color: "#9A9082" },
];

const BY_KEY = new Map(CATEGORIES.map((c) => [c.key, c]));
const FALLBACK: CategoryMeta = CATEGORIES[CATEGORIES.length - 1];

export function categoryMeta(key: string | null | undefined): CategoryMeta {
  if (!key) return FALLBACK;
  return BY_KEY.get(key) ?? FALLBACK;
}

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
  { key: "cinema", label: "Кино", glyph: "🎬", color: "#5C6BC0" },
  { key: "standup", label: "Стендап", glyph: "🎤", color: "#E08A3C" },
  { key: "festival", label: "Фестивали", glyph: "🎪", color: "#4FA487" },
  { key: "lecture", label: "Лекции", glyph: "🎓", color: "#5784C2" },
  { key: "tour", label: "Экскурсии", glyph: "🗺️", color: "#8A9A52" },
  { key: "party", label: "Вечеринки", glyph: "🥂", color: "#A85B92" },
  { key: "quest", label: "Квесты", glyph: "🗝️", color: "#A24F54" },
  { key: "kids", label: "Детям", glyph: "🧸", color: "#5BC0B6" },
  { key: "other", label: "Другое", glyph: "✨", color: "#9A9082" },
];

const BY_KEY = new Map(CATEGORIES.map((c) => [c.key, c]));
const ORDER = new Map(CATEGORIES.map((c, i) => [c.key, i]));
const FALLBACK: CategoryMeta = CATEGORIES[CATEGORIES.length - 1];

export function categoryMeta(key: string | null | undefined): CategoryMeta {
  if (!key) return FALLBACK;
  return BY_KEY.get(key) ?? FALLBACK;
}

// Canonical position of a category (unknown keys sort last). Lets UI render a set
// of picked categories in the SAME stable order as the grid, not tap order.
export function categoryOrder(key: string): number {
  return ORDER.get(key) ?? CATEGORIES.length;
}

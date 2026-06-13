export type CategoryMeta = {
  key: string;
  label: string;
  glyph: string;
  color: string;
};

// Vivid, mutually distinct hues that pop against a muted basemap.
export const CATEGORIES: CategoryMeta[] = [
  { key: "concert", label: "Концерты", glyph: "🎵", color: "#FF4D6D" },
  { key: "theatre", label: "Театр", glyph: "🎭", color: "#FFB020" },
  { key: "exhibition", label: "Выставки", glyph: "🖼️", color: "#A66BFF" },
  { key: "standup", label: "Стендап", glyph: "🎤", color: "#FF7A1A" },
  { key: "festival", label: "Фестивали", glyph: "🎪", color: "#1FCF9A" },
  { key: "lecture", label: "Лекции", glyph: "🎓", color: "#4D96FF" },
  { key: "kids", label: "Детям", glyph: "🧸", color: "#2DD4D4" },
  { key: "other", label: "Другое", glyph: "✨", color: "#8B93A7" },
];

const BY_KEY = new Map(CATEGORIES.map((c) => [c.key, c]));
const FALLBACK: CategoryMeta = CATEGORIES[CATEGORIES.length - 1];

export function categoryMeta(key: string | null | undefined): CategoryMeta {
  if (!key) return FALLBACK;
  return BY_KEY.get(key) ?? FALLBACK;
}

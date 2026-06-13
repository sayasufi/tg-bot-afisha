// VITRINE "vinyl-cut" icon set — bespoke 24×24 pictograms, reductive like
// exhibition wayfinding signage. Solid fill (reads as cut vinyl) using
// currentColor. One source of truth (inner markup) feeds both the React
// <CategoryIcon> and the map divIcon HTML strings.

// Inner SVG markup per category key (no <svg> wrapper, fill = currentColor).
// Each is a bold, distinct silhouette so categories are instantly told apart
// on the monochrome white-cube map.
export const ICON_MARKUP: Record<string, string> = {
  // concert — eighth note
  concert: '<circle cx="8" cy="18" r="3.2"/><rect x="10.6" y="5" width="1.9" height="13"/><path d="M12.5 5l6-1.6v3.4l-6 1.6z"/>',
  // theatre — comedy mask (eyes + smile cut out)
  theatre:
    '<path fill-rule="evenodd" d="M6 3h12v7c0 5.5-2.7 10.5-6 10.5S6 15.5 6 10V3zM8.2 9a1.3 1.3 0 1 0 2.6 0 1.3 1.3 0 1 0-2.6 0zM13.2 9a1.3 1.3 0 1 0 2.6 0 1.3 1.3 0 1 0-2.6 0zM9 14c1 1.3 2 1.9 3 1.9s2-.6 3-1.9c-1 .7-2 1-3 1s-2-.3-3-1z"/>',
  // exhibition — framed landscape (sun + mountains inside a frame)
  exhibition:
    '<path fill-rule="evenodd" d="M3 5h18v14H3V5zm2 2v10h14V7H5z"/><circle cx="8.5" cy="10" r="1.7"/><path d="M5 17l4.5-5.6 3 3.3L16 10l3 7z"/>',
  // standup — microphone on a stand
  standup:
    '<path d="M12 3a4 4 0 0 0-4 4v3a4 4 0 0 0 8 0V7a4 4 0 0 0-4-4z"/><path d="M6 10a6 6 0 0 0 12 0h-1.8a4.2 4.2 0 0 1-8.4 0z"/><rect x="11" y="16.4" width="2" height="3.4"/><rect x="8.4" y="19.6" width="7.2" height="1.9"/>',
  // festival — bunting garland with hanging flags
  festival:
    '<path d="M3 5c6-2.2 12-2.2 18 0v1.8c-6-2.2-12-2.2-18 0z"/><path d="M4.5 6.6l2.4 4.6 2.4-4.6z"/><path d="M9.6 7l2.4 4.6 2.4-4.6z"/><path d="M14.7 6.6l2.4 4.6 2.4-4.6z"/>',
  // lecture — graduation cap
  lecture: '<path d="M12 4 1.5 9 12 14l8.5-4.05V15h1.6V9z"/><path d="M6 12.2V16c0 1.4 2.7 2.8 6 2.8s6-1.4 6-2.8v-3.8l-6 2.9z"/>',
  // kids — balloon
  kids: '<path d="M12 3c3.5 0 6.3 2.9 6.3 6.6 0 3.9-3.1 6.5-5.2 7.5.3.4.5.8.5 1.3 0 1-.9 1.8-1.6 1.8s-1.6-.8-1.6-1.8c0-.5.2-.9.5-1.3C8.8 16.1 5.7 13.5 5.7 9.6 5.7 5.9 8.5 3 12 3z"/>',
  // other — four-point sparkle
  other: '<path d="M12 3c.6 4.8 3.6 7.8 8.4 8.4-4.8.6-7.8 3.6-8.4 8.4-.6-4.8-3.6-7.8-8.4-8.4C8.4 10.8 11.4 7.8 12 3z"/>',
};

function inner(key: string | null | undefined): string {
  return (key && ICON_MARKUP[key]) || ICON_MARKUP.other;
}

// Full <svg> string for embedding in Leaflet divIcon HTML.
export function categorySvg(key: string | null | undefined, size = 18): string {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="currentColor" aria-hidden="true">${inner(key)}</svg>`;
}

// React component for inline use (chips, sheet, lists).
export function CategoryIcon({ cat, size = 16, className }: { cat: string | null | undefined; size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      className={className}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: inner(cat) }}
    />
  );
}

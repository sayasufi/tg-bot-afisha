// VITRINE "vinyl-cut" icon set — bespoke 24×24 pictograms, reductive like
// exhibition wayfinding signage. Solid fill (reads as cut vinyl) using
// currentColor. One source of truth (inner markup) feeds both the React
// <CategoryIcon> and the map divIcon HTML strings.

// Inner SVG markup per category key (no <svg> wrapper, fill = currentColor).
export const ICON_MARKUP: Record<string, string> = {
  // concert — equaliser bars
  concert:
    '<rect x="3" y="13" width="2.7" height="8"/><rect x="7.6" y="8" width="2.7" height="13"/><rect x="12.2" y="3" width="2.7" height="18"/><rect x="16.8" y="11" width="2.7" height="10"/>',
  // theatre — two proscenium curtains meeting at a centre split
  theatre:
    '<path d="M4 4h7v16c-3.2 0-5.6-1-7-3z"/><path d="M20 4h-7v16c3.2 0 5.6-1 7-3z"/>',
  // exhibition — framed canvas with a raking diagonal
  exhibition:
    '<path fill-rule="evenodd" d="M4 4h16v16H4V4zm2.4 2.4v11.2h11.2V6.4H6.4z"/><path d="M7.2 16.2l6.6-8.6 1.7 1.3-6.6 8.6z"/>',
  // standup — freestanding microphone
  standup: '<circle cx="12" cy="8" r="4.2"/><rect x="11" y="11.5" width="2" height="6.5"/><rect x="7.5" y="18" width="9" height="2"/>',
  // festival — tent with an apex pennant
  festival: '<path d="M12 5l8.5 15.5H3.5z"/><path d="M11.2 5.4V1.6h4.2l-1.5 1.3 1.5 1.3z"/>',
  // lecture — speaker's podium
  lecture: '<path d="M6.4 6h11.2l1 4.6H5.4z"/><rect x="11" y="10.6" width="2" height="7.4"/><rect x="6.4" y="18" width="11.2" height="2"/>',
  // kids — paper boat
  kids: '<path d="M3 12.4h18l-3.2 5.2H6.2z"/><path d="M11 3.2v8.2H5.2z"/><rect x="3" y="19" width="18" height="1.6"/>',
  // other — eight-ray asterisk (the editorial footnote mark)
  other:
    '<rect x="11" y="3" width="2" height="18"/><rect x="11" y="3" width="2" height="18" transform="rotate(45 12 12)"/><rect x="11" y="3" width="2" height="18" transform="rotate(90 12 12)"/><rect x="11" y="3" width="2" height="18" transform="rotate(135 12 12)"/>',
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

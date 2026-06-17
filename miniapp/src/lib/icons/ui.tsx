// Unified UI action icons — one 24 box, one 2.2 stroke, round caps/joins, so
// search, close, share, like and menu render at identical weight and footprint
// everywhere they appear.
type UiProps = { size?: number; className?: string };

function strokeProps(size: number, className?: string) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
}

export function IconSearch({ size = 18, className }: UiProps) {
  return (
    <svg {...strokeProps(size, className)}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <line x1="15.6" y1="15.6" x2="21" y2="21" />
    </svg>
  );
}

export function IconClose({ size = 18, className }: UiProps) {
  return (
    <svg {...strokeProps(size, className)}>
      <line x1="6" y1="6" x2="18" y2="18" />
      <line x1="18" y1="6" x2="6" y2="18" />
    </svg>
  );
}

export function IconShare({ size = 18, className }: UiProps) {
  return (
    <svg {...strokeProps(size, className)}>
      <path d="M12 3v12" />
      <path d="M8 6.5 12 3l4 3.5" />
      <path d="M8 9H6.5A2.5 2.5 0 0 0 4 11.5V18a2.5 2.5 0 0 0 2.5 2.5h11A2.5 2.5 0 0 0 20 18v-6.5A2.5 2.5 0 0 0 17.5 9H16" />
    </svg>
  );
}

export function IconMenu({ size = 18, className }: UiProps) {
  return (
    <svg {...strokeProps(size, className)}>
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
    </svg>
  );
}

// "List view" — leading dots + lines (distinct from IconMenu's plain ☰, which is the
// drawer). Dots are filled so they read as bullets at this weight.
export function IconList({ size = 18, className }: UiProps) {
  return (
    <svg {...strokeProps(size, className)}>
      <line x1="9" y1="7" x2="20" y2="7" />
      <line x1="9" y1="12" x2="20" y2="12" />
      <line x1="9" y1="17" x2="20" y2="17" />
      <circle cx="4.6" cy="7" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="4.6" cy="12" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="4.6" cy="17" r="1.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconHeart({ size = 18, className, filled = false }: UiProps & { filled?: boolean }) {
  return (
    <svg {...strokeProps(size, className)} fill={filled ? "currentColor" : "none"}>
      <path d="M12 20.4S4 15.5 4 9.7A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 8 2.7c0 5.8-8 10.7-8 10.7Z" />
    </svg>
  );
}

// "Add to calendar" — a simple calendar with a plus.
export function IconCalendar({ size = 18, className }: UiProps) {
  return (
    <svg {...strokeProps(size, className)}>
      <rect x="3.5" y="5" width="17" height="15.5" />
      <line x1="3.5" y1="9.5" x2="20.5" y2="9.5" />
      <line x1="8" y1="3" x2="8" y2="6.5" />
      <line x1="16" y1="3" x2="16" y2="6.5" />
      <line x1="12" y1="12.5" x2="12" y2="17.5" />
      <line x1="9.5" y1="15" x2="14.5" y2="15" />
    </svg>
  );
}

// "All categories" mark — a filled 2×2 grid (reads as "everything").
export function IconGrid({ size = 18, className }: UiProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <rect x="3.5" y="3.5" width="7" height="7" />
      <rect x="13.5" y="3.5" width="7" height="7" />
      <rect x="3.5" y="13.5" width="7" height="7" />
      <rect x="13.5" y="13.5" width="7" height="7" />
    </svg>
  );
}

// Signature "print proof" layer over VITRINE: a global photocopy/halftone texture
// and the running gallery ticker. (The corner crop marks were removed at the owner's
// request — they read as stray black L's at the screen edges.) Purely decorative
// (pointer-events none), so it never interferes.

export function ProofFrame() {
  return (
    <div className="proof" aria-hidden="true">
      <span className="photocopy" />
    </div>
  );
}

// A continuous mono ticker. Two identical tracks scroll -50% for a seamless
// loop. `text` is the already-joined status line. Tapping it opens the listing.
// When `live`, the cue becomes a pulsing cinnabar dot (events happening now).
export function Ticker({ text, live = false, onClick }: { text: string; live?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className={`ticker${live ? " ticker--live" : ""}`} aria-label="Все события" onClick={onClick}>
      <span className="ticker__cue" aria-hidden="true">
        <span className="ticker__wave">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <i key={i} style={{ ["--i" as string]: i }} />
          ))}
        </span>
      </span>
      <div className="ticker__track">
        <span>{text}</span>
        <span>{text}</span>
      </div>
    </button>
  );
}

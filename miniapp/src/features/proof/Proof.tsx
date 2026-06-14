// Signature "print proof" layer over VITRINE: printer's crop marks +
// registration crosshairs framing the screen, a global photocopy/halftone
// texture, and a running gallery ticker. Purely decorative (pointer-events
// none), so it never interferes with interaction.

export function ProofFrame() {
  return (
    <div className="proof" aria-hidden="true">
      <span className="photocopy" />
      <span className="proof__crop proof__crop--tl" />
      <span className="proof__crop proof__crop--tr" />
      <span className="proof__crop proof__crop--bl" />
      <span className="proof__crop proof__crop--br" />
      <span className="proof__reg proof__reg--l">✛</span>
      <span className="proof__reg proof__reg--r">✛</span>
    </div>
  );
}

// A continuous mono ticker. Two identical tracks scroll -50% for a seamless
// loop. `text` is the already-joined status line. Tapping it opens the listing.
// When `live`, the cue becomes a pulsing cinnabar dot (events happening now).
export function Ticker({ text, live = false, onClick }: { text: string; live?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className={`ticker${live ? " ticker--live" : ""}`} aria-label="Все события" onClick={onClick}>
      <span className="ticker__cue">{live ? <span className="ticker__live" /> : "▸"}</span>
      <div className="ticker__track">
        <span>{text}</span>
        <span>{text}</span>
      </div>
    </button>
  );
}

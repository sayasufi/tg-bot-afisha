import { Component, type CSSProperties, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

// One render-time exception (a malformed date, a bad image decode) would
// otherwise white-screen the whole map. Catch it and offer a recoverable
// "reload" fallback instead of a dead app.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("App crashed:", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    // Inline styles on purpose: the fallback must render even if a CSS chunk is
    // what failed to load.
    return (
      <div style={S.wrap}>
        <div style={S.box}>
          <div style={S.title}>что-то сломалось</div>
          <div style={S.hint}>Перезагрузи — это починит экран.</div>
          <button type="button" style={S.btn} onClick={() => window.location.reload()}>
            Перезагрузить
          </button>
        </div>
      </div>
    );
  }
}

// Inline + on-brand (VITRINE): plaster wall, ink text, black-on-acid button, hairline
// frame, brand font stack with a sans fallback (a failed CSS chunk can't undo this).
const BRAND = "'Unbounded', 'Familjen Grotesk', system-ui, sans-serif";
const MONO = "'Martian Mono', ui-monospace, monospace";
const S: Record<string, CSSProperties> = {
  wrap: {
    position: "fixed",
    inset: 0,
    background: "#F4F4EF",
    color: "#0B0B0B",
    display: "grid",
    placeItems: "center",
    padding: "24px",
    fontFamily: BRAND,
    zIndex: 99999,
  },
  box: {
    maxWidth: 320,
    textAlign: "center",
    padding: "28px 22px",
    background: "#FFFFFF",
    boxShadow: "inset 0 0 0 1px #0B0B0B",
  },
  title: { fontSize: 22, fontWeight: 700, letterSpacing: "-0.03em", textTransform: "lowercase", marginBottom: 10 },
  hint: { fontSize: 13, fontFamily: MONO, color: "#6e6e66", marginBottom: 22, lineHeight: 1.5 },
  btn: {
    border: 0,
    boxShadow: "inset 0 0 0 1px #0B0B0B, 1.6px 1.6px 0 #E63312",
    background: "#CCFF00",
    color: "#0B0B0B",
    fontFamily: BRAND,
    fontWeight: 700,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    fontSize: 12,
    padding: "13px 24px",
    cursor: "pointer",
  },
};

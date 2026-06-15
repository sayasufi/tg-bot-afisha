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
          <div style={S.hint}>Попробуйте перезагрузить — это починит экран.</div>
          <button type="button" style={S.btn} onClick={() => window.location.reload()}>
            Перезагрузить
          </button>
        </div>
      </div>
    );
  }
}

const S: Record<string, CSSProperties> = {
  wrap: {
    position: "fixed",
    inset: 0,
    background: "#14130e",
    color: "#f1ecde",
    display: "grid",
    placeItems: "center",
    padding: "24px",
    fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
    zIndex: 99999,
  },
  box: { maxWidth: 320, textAlign: "center" },
  title: { fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: 10 },
  hint: { fontSize: 14, color: "#9a958a", marginBottom: 22, lineHeight: 1.4 },
  btn: {
    border: "1px solid #3a3830",
    background: "#ffb02e",
    color: "#0b0b0b",
    fontWeight: 700,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    fontSize: 13,
    padding: "12px 22px",
    cursor: "pointer",
  },
};

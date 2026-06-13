import { Fragment, type ReactNode } from "react";

// Wrap occurrences of `query` in <mark> — safe (splits the string, no innerHTML).
// Every segment is keyed by its source offset so keys stay stable across renders.
export function Highlight({ text, query }: { text: string; query?: string | null }): ReactNode {
  const q = (query || "").trim();
  if (!q) return text;
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const out: ReactNode[] = [];
  let i = 0;
  while (i < text.length) {
    const idx = lower.indexOf(ql, i);
    if (idx === -1) {
      out.push(<Fragment key={`t${i}`}>{text.slice(i)}</Fragment>);
      break;
    }
    if (idx > i) out.push(<Fragment key={`t${i}`}>{text.slice(i, idx)}</Fragment>);
    out.push(
      <mark className="hl" key={`m${idx}`}>
        {text.slice(idx, idx + q.length)}
      </mark>,
    );
    i = idx + q.length;
  }
  return out;
}

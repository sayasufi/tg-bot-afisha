import type { ReactNode } from "react";

// Wrap occurrences of `query` in <mark> — safe (splits the string, no innerHTML).
export function Highlight({ text, query }: { text: string; query?: string | null }): ReactNode {
  const q = (query || "").trim();
  if (!q) return text;
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const out: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < text.length) {
    const idx = lower.indexOf(ql, i);
    if (idx === -1) {
      out.push(text.slice(i));
      break;
    }
    if (idx > i) out.push(text.slice(i, idx));
    out.push(
      <mark className="hl" key={k++}>
        {text.slice(idx, idx + q.length)}
      </mark>,
    );
    i = idx + q.length;
  }
  return out;
}

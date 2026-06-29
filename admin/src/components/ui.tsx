import { ReactNode } from "react";

export const fmtNum = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("ru-RU");

export const fmtPct = (x: number | null | undefined) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;

export function agoHours(h: number | null | undefined): string {
  if (h == null) return "—";
  if (h < 1) return `${Math.round(h * 60)} мин`;
  if (h < 48) return `${h.toFixed(1)} ч`;
  return `${Math.round(h / 24)} дн`;
}

export function StatCard({
  num,
  label,
  sub,
  tone,
  accent,
}: {
  num: ReactNode;
  label: string;
  sub?: ReactNode;
  tone?: "warn";
  accent?: boolean;
}) {
  return (
    <div className={"statcard" + (accent ? " statcard--accent" : "")}>
      <div className={"statcard__num" + (tone === "warn" ? " statcard__num--warn" : "")}>{num}</div>
      <div className="statcard__label">{label}</div>
      {sub != null && <div className="statcard__sub">{sub}</div>}
    </div>
  );
}

type Kind = "ok" | "warn" | "down" | "off";

export function Badge({ kind, children }: { kind: Kind; children: ReactNode }) {
  return <span className={`badge badge--${kind}`}>{children}</span>;
}

export function Dot({ kind }: { kind: Kind }) {
  return <span className={`dot dot--${kind}`} />;
}

export function Spark({ values }: { values: number[] }) {
  const max = Math.max(1, ...values);
  return (
    <div className="spark">
      {values.map((v, i) => (
        <div
          key={i}
          className={"spark__bar" + (i === values.length - 1 ? " spark__bar--last" : "")}
          style={{ height: `${Math.max(3, (v / max) * 100)}%` }}
          title={String(v)}
        />
      ))}
    </div>
  );
}

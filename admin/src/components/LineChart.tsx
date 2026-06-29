type Pt = { label: string; value: number };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const base = Math.pow(10, exp);
  const f = v / base;
  const n = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return n * base;
}

function fmtCompact(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1).replace(".0", "") + "k";
  return String(Math.round(n));
}

// Catmull-Rom → кубический Безье: плавная линия через точки.
function smoothPath(pts: [number, number][]): string {
  if (!pts.length) return "";
  if (pts.length === 1) return `M ${pts[0][0]} ${pts[0][1]}`;
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2[0]} ${p2[1]}`;
  }
  return d;
}

export function LineChart({ data }: { data: Pt[] }) {
  if (!data || !data.length) return <div className="state">нет данных за период</div>;

  const W = 1100, H = 180, padL = 46, padR = 16, padT = 14, padB = 26;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const max = niceMax(Math.max(...data.map((d) => d.value)));
  const xAt = (i: number) => padL + (data.length <= 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const yAt = (v: number) => padT + innerH - (v / max) * innerH;
  const pts: [number, number][] = data.map((d, i) => [xAt(i), yAt(d.value)]);
  const line = smoothPath(pts);
  const area = line ? `${line} L ${pts[pts.length - 1][0]} ${padT + innerH} L ${pts[0][0]} ${padT + innerH} Z` : "";

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => (max / ticks) * i);
  const xStep = data.length > 16 ? Math.ceil(data.length / 14) : 1;

  return (
    <svg className="linechart" viewBox={`0 0 ${W} ${H}`}>
      {yTicks.map((t, i) => {
        const yy = yAt(t);
        return (
          <g key={i}>
            <line x1={padL} y1={yy} x2={W - padR} y2={yy} className="lc-grid" />
            <text x={padL - 8} y={yy + 4} className="lc-ylabel" textAnchor="end">{fmtCompact(t)}</text>
          </g>
        );
      })}
      {area && <path d={area} className="lc-area" />}
      {line && <path d={line} className="lc-line" />}
      {pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={i === pts.length - 1 ? 4 : 2.5} className={i === pts.length - 1 ? "lc-dot lc-dot--last" : "lc-dot"}>
          <title>{`${data[i].label}: ${data[i].value}`}</title>
        </circle>
      ))}
      {data.map((d, i) =>
        i % xStep === 0 || i === data.length - 1 ? (
          <text key={i} x={xAt(i)} y={H - 7} className="lc-xlabel" textAnchor="middle">{d.label}</text>
        ) : null
      )}
    </svg>
  );
}

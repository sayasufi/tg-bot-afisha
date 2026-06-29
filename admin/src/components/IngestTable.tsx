import { Badge, agoHours } from "./ui";

export function IngestTable({ rows }: { rows: any[] }) {
  if (!rows || !rows.length) return <div className="state">нет источников</div>;
  return (
    <div className="tablewrap">
      <table className="table">
        <thead>
          <tr>
            <th>источник</th>
            <th>тип</th>
            <th>последний статус</th>
            <th>когда</th>
            <th className="num">лаг</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const st: string | null = r.last_status;
            const kind = st === "success" ? "ok" : st === "running" ? "warn" : st ? "down" : "off";
            const when = r.last_finished || r.last_started;
            return (
              <tr key={r.name}>
                <td>
                  {r.name}
                  {!r.is_active && <span className="badge badge--off" style={{ marginLeft: 8 }}>выкл</span>}
                </td>
                <td className="muted">{r.kind}</td>
                <td>{st ? <Badge kind={kind as any}>{st}</Badge> : <span className="muted">— нет прогонов</span>}</td>
                <td className="muted">{when ? new Date(when).toLocaleString("ru-RU") : "—"}</td>
                <td className="num">{agoHours(r.lag_hours)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import { Badge, agoHours } from "./ui";

// Источники сгруппированы по семейству (afisha_ru/kudago/telegram_public/timepad/yandex_afisha) —
// 376 per-city источников свернуты в ~5 строк. lag_hours = свежесть самого свежего прогона в семействе.
export function IngestTable({ rows }: { rows: any[] }) {
  if (!rows || !rows.length) return <div className="state">нет источников</div>;
  return (
    <div className="tablewrap">
      <table className="table">
        <thead>
          <tr>
            <th>источник</th>
            <th className="num">активно</th>
            <th className="num">успешных</th>
            <th>свежесть</th>
            <th>последний прогон</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const lag: number | null = r.lag_hours;
            const kind = lag == null ? "down" : lag < 6 ? "ok" : lag < 24 ? "warn" : "down";
            return (
              <tr key={r.family}>
                <td>{r.family}</td>
                <td className="num">
                  {r.active}/{r.sources}
                </td>
                <td className="num">
                  {r.ok}
                  {r.failed ? <span className="muted"> · {r.failed}✗</span> : null}
                </td>
                <td>
                  <Badge kind={kind as any}>{lag == null ? "нет прогонов" : agoHours(lag)}</Badge>
                </td>
                <td className="muted">{r.latest_finish ? new Date(r.latest_finish).toLocaleString("ru-RU") : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

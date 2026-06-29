import { useState } from "react";

import { Badge, StatCard, fmtNum } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

const STATE_KIND: Record<string, "ok" | "warn" | "down" | "off"> = {
  COMPLETED: "ok", RUNNING: "warn", PENDING: "warn", SCHEDULED: "warn", FAILED: "down", CRASHED: "down", CANCELLED: "off",
};
const STATE_LABEL: Record<string, string> = {
  COMPLETED: "успех", RUNNING: "идёт", PENDING: "ожидание", SCHEDULED: "в очереди", FAILED: "ошибка", CRASHED: "краш", CANCELLED: "отменён",
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} дн назад`;
}

function ThTable({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="tablewrap" style={{ flex: 1, minWidth: 280 }}>
      <table className="table">
        <thead>
          <tr>
            <th>{title}</th>
            <th style={{ textAlign: "right" }}>порог</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="muted">{k}</td>
              <td className="num" style={{ textAlign: "right" }}>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Dedup() {
  const { data, error, loading, reload } = useApi<any>("/dedup/status");
  const flows = useApi<any>("/flows", 20000);
  const heal = (flows.data?.flows ?? []).find((f: any) => f.name === "self-heal-dedup");
  const [busy, setBusy] = useState(false);

  const runHeal = async () => {
    if (!heal) return;
    setBusy(true);
    try {
      await apiPost("/ops/run", { deployment_id: heal.id, name: heal.name });
    } finally {
      setTimeout(() => {
        setBusy(false);
        flows.reload();
        reload();
      }, 1500);
    }
  };

  const t = data?.thresholds;
  const c = data?.counts;

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">дубликаты</h1>
          <div className="page__sub">прозрачность дедупа — пороги, состояние, самоисцеление</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="section__title">текущее состояние</div>
          <div className="statgrid">
            <StatCard num={fmtNum(c.events_active)} label="активных событий" accent />
            <StatCard num={fmtNum(c.venues_total)} label="площадок" />
            <StatCard
              num={fmtNum(c.near_dup_venues)}
              label="дубль-пины площадок"
              tone={c.near_dup_venues > 0 ? "warn" : undefined}
              sub="одноимённые в 200м · норма 0"
            />
            <StatCard num={fmtNum(c.events_multi_occurrence)} label="событий с >1 сессией" sub="контекст, не дефект" />
          </div>

          <div className="section__title">самоисцеление</div>
          <div className="panelrow">
            <div className="tablewrap" style={{ flex: 1 }}>
              <table className="table">
                <tbody>
                  <tr>
                    <td className="muted">процесс</td>
                    <td>self-heal-dedup · слияние площадок + событий + resplit</td>
                  </tr>
                  <tr>
                    <td className="muted">статус</td>
                    <td>
                      {heal?.last_state ? (
                        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                          <Badge kind={STATE_KIND[heal.last_state] ?? "off"}>{STATE_LABEL[heal.last_state] ?? heal.last_state}</Badge>
                          <span className="muted">{ago(heal.last_start)}</span>
                        </span>
                      ) : (
                        <span className="muted">— нет прогонов</span>
                      )}
                    </td>
                  </tr>
                  <tr>
                    <td className="muted">расписание</td>
                    <td className="muted">каждые 15 минут (авто)</td>
                  </tr>
                  <tr>
                    <td className="muted">запуск</td>
                    <td>
                      <button className="iconbtn" onClick={runHeal} disabled={!heal || busy}>
                        {busy ? "запущено…" : "запустить сейчас"}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="section__title">пороги дедупа</div>
          <div className="chart-hint">
            Очереди ручного ревью нет: слияния автоматические и необратимые (дубль склеивается в канонический). Кандидаты со
            скором 0.72–0.86 не сливаются и не хранятся. Ниже — действующие пороги (читаются из констант кода).
          </div>
          <div className="panelrow">
            <ThTable
              title="События"
              rows={[
                ["авто-слияние (скор)", `≥ ${t.event_auto_merge}`],
                ["на ревью (скор)", `${t.event_review}–${(t.event_auto_merge - 0.01).toFixed(2)}`],
                ["совпадение названия — авто", `≥ ${t.title_ratio_auto}`],
                ["совпадение названия — fuzzy", `≥ ${t.title_ratio_fuzzy}`],
              ]}
            />
            <ThTable
              title="Площадки"
              rows={[
                ["сильное имя — авто", `≥ ${t.venue_strong_ratio}`],
                ["co-host (с дубль-пином)", `≥ ${t.venue_cohost_ratio}`],
                ["радиус кандидатов", `${t.venue_radius_m} м`],
                ["co-host радиус", `${t.venue_show_radius_m} м`],
                ["write-time fuzzy", `${t.venue_writetime_fuzzy_m} м`],
                ["write-time tight", `${t.venue_writetime_tight_m} м`],
              ]}
            />
          </div>
        </>
      )}
    </div>
  );
}

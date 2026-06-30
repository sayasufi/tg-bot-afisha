import { StatCard, fmtNum } from "../components/ui";
import { useApi } from "../lib/useApi";

const pctText = (p: number | null) => (p == null ? "—" : `${p}%`);

function CohortCell({ p }: { p: number | null }) {
  // Зелёным к высокому удержанию, тускло к низкому — мгновенно читается по таблице.
  if (p == null) return <td className="num muted">—</td>;
  const hot = p >= 40, mid = p >= 20;
  return <td className="num" style={{ color: hot ? "var(--acid)" : mid ? "var(--ink)" : "var(--ink-dim)", fontWeight: hot ? 600 : 400 }}>{p}%</td>;
}

export function Funnel() {
  const { data, loading, error, reload } = useApi<any>("/funnel", 30000);
  const funnel: any[] = data?.funnel ?? [];
  const cohorts: any[] = data?.cohorts ?? [];
  const bySource: any[] = data?.by_source ?? [];
  const trend: any[] = data?.trend ?? [];
  const loops = data?.loops;
  const maxTrend = Math.max(1, ...trend.map((t) => Math.max(t.new, t.saves)));

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">воронка и удержание</h1>
          <div className="page__sub">источник → открыл → онбординг → город → сохранил → вернулся · когорты D1/D7/D30 · окупаемость рекламы</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="statgrid">
            <StatCard num={fmtNum(funnel[0]?.n ?? 0)} label="всего юзеров" sub={`${data.attributed} с рекламы · ${data.organic} органика`} accent />
            <StatCard num={fmtNum(loops?.total_saves ?? 0)} label="сохранений (intent)" sub="главный north-star сигнал" />
            <StatCard num={fmtNum(loops?.digest_sent ?? 0)} label="получили дайджест" sub="петля возврата D7" />
            <StatCard num={fmtNum(loops?.welcome_nudge ?? 0)} label="получили D1-нудж" sub="петля возврата D1" />
          </div>

          <div className="section__title">воронка</div>
          <div className="tablewrap" style={{ padding: "8px 14px" }}>
            {funnel.map((s, i) => {
              const base = funnel[0]?.n || 1;
              const w = Math.max(2, Math.round(((s.n || 0) / base) * 100));
              const prev = i > 0 ? funnel[i - 1]?.n || 0 : null;
              const drop = prev && prev > 0 ? Math.round((1 - (s.n || 0) / prev) * 100) : null;
              return (
                <div key={s.stage} style={{ display: "flex", alignItems: "center", gap: 12, padding: "6px 0" }}>
                  <div style={{ width: 170, fontSize: 12, color: "var(--ink)" }}>{s.stage}</div>
                  <div style={{ flex: 1, background: "var(--vitrine)", height: 26, position: "relative", border: "1px solid var(--line)" }}>
                    <div style={{ width: `${w}%`, height: "100%", background: i === 0 ? "var(--acid)" : "color-mix(in srgb, var(--acid) 55%, transparent)" }} />
                    <div style={{ position: "absolute", left: 8, top: 0, height: 26, display: "flex", alignItems: "center", fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600 }}>
                      {fmtNum(s.n)} <span className="muted" style={{ marginLeft: 6, fontWeight: 400 }}>{pctText(s.pct)}</span>
                    </div>
                  </div>
                  <div style={{ width: 70, textAlign: "right", fontSize: 11 }} className="muted">
                    {drop != null && i > 0 ? `−${drop}%` : ""}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="section__title">удержание по когортам (неделя входа)</div>
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>когорта</th><th className="num">размер</th><th className="num">D1</th><th className="num">D7</th><th className="num">D30</th></tr></thead>
              <tbody>
                {cohorts.map((c) => (
                  <tr key={c.week}>
                    <td>{c.week}</td><td className="num">{c.size}</td>
                    <CohortCell p={c.d1} /><CohortCell p={c.d7} /><CohortCell p={c.d30} />
                  </tr>
                ))}
                {!cohorts.length && <tr><td colSpan={5} className="muted">нет данных</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="chart-hint">D_N = доля «дозревших» (вошли ≥N дней назад), у кого последнее открытие приложения было спустя ≥N дней после входа.</div>

          <div className="section__title">по источникам привлечения</div>
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>источник</th><th className="num">пришло</th><th className="num">открыли</th><th className="num">сохранили</th><th className="num">вернулись</th><th className="num">% сохр.</th></tr></thead>
              <tbody>
                {bySource.map((s) => (
                  <tr key={s.source}>
                    <td className="code">{s.source}</td>
                    <td className="num">{s.came}</td><td className="num muted">{s.opened}</td>
                    <td className="num" style={s.saved ? { color: "var(--acid)", fontWeight: 600 } : undefined}>{s.saved}</td>
                    <td className="num muted">{s.returned}</td>
                    <td className="num muted">{pctText(s.save_rate)}</td>
                  </tr>
                ))}
                {!bySource.length && <tr><td colSpan={6} className="muted">пока нет привлечённых по меткам — запусти закупку</td></tr>}
              </tbody>
            </table>
          </div>

          <div className="section__title">тренд 30 дней — новые юзеры · сохранения</div>
          <div className="tablewrap" style={{ padding: 14 }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90 }}>
              {trend.map((t) => (
                <div key={t.day} title={`${t.day}: +${t.new} новых, ${t.saves} сохр.`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 2, minWidth: 4 }}>
                  <div style={{ height: `${(t.new / maxTrend) * 70}px`, background: "var(--acid)" }} />
                  <div style={{ height: `${(t.saves / maxTrend) * 70}px`, background: "var(--cinnabar)" }} />
                </div>
              ))}
              {!trend.length && <div className="muted">нет активности за 30 дней</div>}
            </div>
            <div className="chart-hint" style={{ marginTop: 6 }}>
              <span style={{ color: "var(--acid)" }}>■</span> новые юзеры · <span style={{ color: "var(--cinnabar)" }}>■</span> сохранения
            </div>
          </div>
        </>
      )}
    </div>
  );
}

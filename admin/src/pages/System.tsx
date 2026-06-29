import { StatCard, fmtNum } from "../components/ui";
import { useApi } from "../lib/useApi";

export function System() {
  const { data, error, loading, reload } = useApi<any>("/ops/system", 60000);
  const tables = data?.tables ?? [];
  const maxBytes = Math.max(1, ...tables.map((t: any) => t.bytes));

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">бэкапы и сервис</h1>
          <div className="page__sub">размер базы и крупнейшие таблицы · контроль роста</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="statgrid">
            <StatCard num={data.db_size} label="размер базы данных" accent />
            <StatCard num={fmtNum(tables.length)} label="таблиц в топе" sub="по занимаемому месту" />
          </div>

          <div className="bcast-note">
            Бэкапы БД делает <b>ежедневный pg_dump</b> по хост-крону (вне этой панели). Если таблица
            <span className="code"> source_runs</span> сильно растёт — её можно подчистить процессом
            <span className="code"> sweep-stale-runs</span> из раздела «Процессы».
          </div>

          <div className="section__title">крупнейшие таблицы</div>
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr><th>таблица</th><th className="num">размер</th><th className="num">строк</th><th>доля</th></tr>
              </thead>
              <tbody>
                {tables.map((t: any) => (
                  <tr key={t.name}>
                    <td className="code">{t.name}</td>
                    <td className="num">{t.size}</td>
                    <td className="num muted">{fmtNum(t.rows)}</td>
                    <td style={{ width: 180 }}>
                      <div style={{ height: 8, background: "var(--ink-dim)", width: `${Math.max(3, (t.bytes / maxBytes) * 100)}%` }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

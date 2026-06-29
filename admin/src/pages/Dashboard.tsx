import { IngestTable } from "../components/IngestTable";
import { Spark, StatCard, fmtNum, fmtPct } from "../components/ui";
import { useApi } from "../lib/useApi";

const ACTION_LABELS: Record<string, string> = {
  click: "открытий",
  route: "маршрутов",
  share: "шеров",
  reminder: "напоминаний",
  calendar: "в календарь",
};

export function Dashboard() {
  const { data, error, loading, reload } = useApi<any>("/overview", 60000);

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">дашборд</h1>
          {data && <div className="page__sub page__meta">обновлено {new Date(data.as_of).toLocaleString("ru-RU")}</div>}
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="section__title">каталог</div>
          <div className="statgrid">
            <StatCard num={fmtNum(data.catalog.active)} label="активных событий" sub={`всего ${fmtNum(data.catalog.total)}`} />
            <StatCard num={fmtPct(data.catalog.image_share)} label="с фото" sub={`${fmtNum(data.catalog.with_image)} шт`} />
            <StatCard num={fmtPct(data.catalog.future_share)} label="будущих" sub={`${fmtNum(data.catalog.future)} шт`} />
            <StatCard num={fmtNum(data.catalog.new_24h)} label="новых за 24ч" />
            <StatCard num={fmtNum(data.catalog.new_7d)} label="новых за 7д" />
            <StatCard num={fmtNum(data.catalog.venues)} label="площадок" />
          </div>

          <div className="section__title">пользователи</div>
          <div className="statgrid">
            <StatCard num={fmtNum(data.users.total)} label="всего" />
            <StatCard num={fmtNum(data.users.active_7d)} label="активных за 7д" />
            <StatCard num={fmtNum(data.users.new_7d)} label="новых за 7д" />
            <StatCard num={fmtNum(data.users.digest_optin)} label="подписаны на дайджест" />
          </div>

          <div className="section__title">north-star · недельная активность</div>
          <div className="statgrid">
            <StatCard
              num={fmtNum(data.north_star.wau?.[0]?.users)}
              label={`WAU · ${data.north_star.wau?.[0]?.week ?? ""}`}
              sub={
                data.north_star.wau?.length ? (
                  <Spark values={[...data.north_star.wau].reverse().map((w: any) => w.users)} />
                ) : null
              }
            />
            {Object.entries(ACTION_LABELS).map(([k, label]) => (
              <StatCard key={k} num={fmtNum(data.north_star.actions_7d?.[k] ?? 0)} label={label} sub="за 7д" />
            ))}
          </div>

          <div className="section__title">ингест по источникам</div>
          <IngestTable rows={data.ingest} />
        </>
      )}
    </div>
  );
}

import { LineChart } from "../components/LineChart";
import { useApi } from "../lib/useApi";

const ACTION_LABELS: Record<string, string> = {
  click: "открытия карточек",
  route: "маршруты к месту",
  share: "шеры «пойдём»",
  reminder: "напоминания",
};

export function Analytics() {
  const { data, error, loading, reload } = useApi<any>("/stats/timeseries", 60000);
  const actionKinds = data?.actions ? Object.keys(data.actions) : [];

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">аналитика</h1>
          <div className="page__sub">тренды вовлечённости и роста каталога</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="section__title">WAU · недельная аудитория (8 недель, № ISO-недели)</div>
          <LineChart data={data.wau} />

          {actionKinds.map((k) => (
            <div key={k}>
              <div className="section__title">действия за 14 дней · {ACTION_LABELS[k] ?? k}</div>
              <LineChart data={data.actions[k]} />
            </div>
          ))}

          <div className="section__title">новые события по дням · объём ингеста (14 дней)</div>
          <LineChart data={data.new_events} />

          <div className="section__title">новые пользователи по дням (14 дней)</div>
          <LineChart data={data.new_users} />
        </>
      )}
    </div>
  );
}

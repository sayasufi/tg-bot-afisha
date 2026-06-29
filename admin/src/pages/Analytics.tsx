import { ReactNode } from "react";

import { LineChart } from "../components/LineChart";
import { useApi } from "../lib/useApi";

const ACTIONS: Record<string, { label: string; hint: string }> = {
  click: { label: "Открыли событие", hint: "сколько раз открывали карточку события" },
  route: { label: "Построили маршрут", hint: "сколько раз строили маршрут до площадки" },
  share: { label: "Поделились «пойдём?»", hint: "сколько раз отправляли событие другу через кнопку «пойдём?»" },
  reminder: { label: "Поставили напоминание", hint: "сколько раз ставили напоминание на событие" },
};

function Chart({ title, hint, data }: { title: string; hint: string; data: { label: string; value: number }[] }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div className="section__title" style={{ marginBottom: 2 }}>{title}</div>
      <div className="chart-hint">{hint}</div>
      <LineChart data={data} />
    </div>
  );
}

export function Analytics() {
  const { data, error, loading, reload } = useApi<any>("/stats/timeseries", 60000);
  const actionKinds: string[] = data?.actions ? Object.keys(data.actions) : [];

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">аналитика</h1>
          <div className="page__sub">как пользуются приложением и как растёт каталог</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <Chart
            title="Активные пользователи по неделям"
            hint="сколько разных людей заходили и что-то делали за каждую неделю (последние 8 недель)"
            data={data.wau}
          />

          {actionKinds.map((k) => (
            <Chart
              key={k}
              title={`${ACTIONS[k]?.label ?? k} — по дням`}
              hint={`${ACTIONS[k]?.hint ?? ""} (за последние 14 дней)`}
              data={data.actions[k]}
            />
          ))}

          <Chart
            title="Новые события — по дням"
            hint="сколько новых событий подтянулось из источников за день (за 14 дней)"
            data={data.new_events}
          />

          <Chart
            title="Новые пользователи — по дням"
            hint="сколько новых людей впервые зашли за день (за 14 дней)"
            data={data.new_users}
          />
        </>
      )}
    </div>
  );
}

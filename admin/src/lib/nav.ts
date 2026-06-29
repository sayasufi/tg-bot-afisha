export type NavItem = { label: string; to: string; phase?: number };
export type NavGroup = { title: string; items: NavItem[] };

// phase задан → раздел ещё не построен (показываем «Фn» и страницу-заглушку). Без phase → живой раздел.
export const NAV: NavGroup[] = [
  {
    title: "Обзор",
    items: [
      { label: "Дашборд", to: "/" },
      { label: "Аналитика", to: "/analytics", phase: 3 },
      { label: "Здоровье", to: "/health" },
    ],
  },
  {
    title: "Данные",
    items: [
      { label: "События", to: "/events", phase: 3 },
      { label: "Площадки", to: "/venues", phase: 3 },
      { label: "Дедуп", to: "/dedup", phase: 3 },
    ],
  },
  {
    title: "Ингест",
    items: [
      { label: "Источники", to: "/sources", phase: 2 },
      { label: "TG-каналы", to: "/channels", phase: 2 },
      { label: "Города", to: "/cities", phase: 4 },
    ],
  },
  {
    title: "Операции",
    items: [
      { label: "Флоу", to: "/ops/flows", phase: 2 },
      { label: "Maintenance", to: "/ops/data", phase: 2 },
      { label: "Опасные", to: "/ops/danger", phase: 2 },
      { label: "Система", to: "/ops/system", phase: 4 },
    ],
  },
  {
    title: "Люди",
    items: [
      { label: "Пользователи", to: "/users", phase: 4 },
      { label: "Рассылки", to: "/broadcasts", phase: 2 },
    ],
  },
  {
    title: "Реклама",
    items: [{ label: "Посев", to: "/adstat", phase: 4 }],
  },
  {
    title: "Система",
    items: [
      { label: "Настройки", to: "/settings", phase: 3 },
      { label: "Аудит", to: "/audit", phase: 4 },
    ],
  },
];

export const ALL_ITEMS = NAV.flatMap((g) => g.items);

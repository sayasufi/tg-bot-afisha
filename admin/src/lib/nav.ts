export type NavItem = { label: string; to: string; phase?: number };
export type NavGroup = { title: string; items: NavItem[] };

// phase задан → раздел ещё не построен (метка «Фn» + страница-заглушка). Без phase → живой раздел.
// Секции сворачиваемые (аккордеон) — открыта та, что содержит активный маршрут.
export const NAV: NavGroup[] = [
  {
    title: "Обзор",
    items: [
      { label: "Сводка", to: "/" },
      { label: "Аналитика", to: "/analytics", phase: 3 },
      { label: "Здоровье", to: "/health" },
    ],
  },
  {
    title: "Каталог",
    items: [
      { label: "События", to: "/events", phase: 3 },
      { label: "Площадки", to: "/venues", phase: 3 },
      { label: "Дубликаты", to: "/dedup", phase: 3 },
    ],
  },
  {
    title: "Сбор данных",
    items: [
      { label: "Источники", to: "/sources" },
      { label: "TG-каналы", to: "/channels" },
      { label: "Города", to: "/cities", phase: 4 },
    ],
  },
  {
    title: "Операции",
    items: [
      { label: "Процессы", to: "/ops/flows" },
      { label: "Обработка данных", to: "/ops/data", phase: 2 },
      { label: "Опасная зона", to: "/ops/danger", phase: 2 },
      { label: "Бэкапы и сервис", to: "/ops/system", phase: 4 },
    ],
  },
  {
    title: "Аудитория",
    items: [
      { label: "Пользователи", to: "/users", phase: 4 },
      { label: "Рассылки", to: "/broadcasts" },
      { label: "Реклама", to: "/adstat", phase: 4 },
    ],
  },
  {
    title: "Система",
    items: [
      { label: "Настройки", to: "/settings", phase: 3 },
      { label: "Журнал действий", to: "/audit", phase: 4 },
    ],
  },
];

export const ALL_ITEMS = NAV.flatMap((g) => g.items);

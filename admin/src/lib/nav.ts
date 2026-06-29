export type NavItem = { label: string; to: string; phase?: number };
export type NavGroup = { title: string; items: NavItem[] };

// phase задан → раздел ещё не построен (метка «Фn» + страница-заглушка). Без phase → живой раздел.
// Секции сворачиваемые (аккордеон) — открыта та, что содержит активный маршрут.
export const NAV: NavGroup[] = [
  {
    title: "Обзор",
    items: [
      { label: "Сводка", to: "/" },
      { label: "Аналитика", to: "/analytics" },
      { label: "Здоровье", to: "/health" },
    ],
  },
  {
    title: "Каталог",
    items: [
      { label: "События", to: "/events" },
      { label: "Площадки", to: "/venues" },
      { label: "Дубликаты", to: "/dedup" },
    ],
  },
  {
    title: "Сбор данных",
    items: [
      { label: "Источники", to: "/sources" },
      { label: "TG-каналы", to: "/channels" },
      { label: "Города", to: "/cities" },
    ],
  },
  {
    title: "Операции",
    items: [
      { label: "Процессы", to: "/ops/flows" },
      { label: "Обработка данных", to: "/ops/data" },
      { label: "Опасная зона", to: "/ops/danger" },
      { label: "Бэкапы и сервис", to: "/ops/system" },
    ],
  },
  {
    title: "Аудитория",
    items: [
      { label: "Пользователи", to: "/users" },
      { label: "Рассылки", to: "/broadcasts" },
      { label: "Реклама", to: "/adstat" },
    ],
  },
  {
    title: "Система",
    items: [
      { label: "Настройки", to: "/settings" },
      { label: "Журнал действий", to: "/audit" },
    ],
  },
];

export const ALL_ITEMS = NAV.flatMap((g) => g.items);

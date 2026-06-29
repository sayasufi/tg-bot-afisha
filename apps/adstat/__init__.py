"""adstat — изолированный скрапер TG-каналов для рекламного ресёрча.

Собирает статистику каналов-кандидатов (подписчики, ER, охват, накрутка, цитирование)
из Telemetr (чистый JSON-API) и опц. TGStat (HTML), пишет в схему `adstat`.

Запуск standalone:  python -m apps.adstat.run [--dry-run] [user1 user2 ...]
Через Prefect:       flow `scrape-adstat` (см. flows.py / prefect_serve.py)
"""

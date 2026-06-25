# adstat — скрапер TG-каналов для рекламного ресёрча

Изолированный компонент: собирает статистику каналов-кандидатов (для закупки рекламы под бота)
из **Telemetr** (чистый JSON-API) и опц. **TGStat** (HTML) и пишет в отдельную схему БД `adstat`.
Не связан с продуктовым пайплайном (ref/events).

## Что собирает (схема `adstat`)
- `adstat.targets` — список каналов к скрапингу (`username`, `city`, `is_active`).
- `adstat.channels` — реестр (username, peer_id, title, язык, цена рекламы, last_scraped_at).
- `adstat.snapshots` — **append-only** ряд снимков: подписчики, ER, ERR, охват, оценка качества,
  премиум-доля, прирост/мес, индекс цитирования, и флаги фрода `is_scam / is_boosting (накрутка) /
  is_stolen / sanctioned`, + сырой JSON источника. Каждый заход = новая строка → история трендов.

## Источники
| Источник | Транспорт | На сервере | Отдаёт |
|---|---|---|---|
| **Telemetr** | `curl_cffi` → `/api/v1/catalog/channels` | ✅ работает (нет Cloudflare, нужна только сессия `PHPSESSID`, IP не важен) | подписчики, ER, качество, рост, цена, **флаги фрода** |
| **TGStat** | `curl_cffi` → HTML `/channel/@x/stat` | ⚠️ за Cloudflare | подписчики, охват, ERR, индекс цитирования |

**Cloudflare / IP (важно).** `cf_clearance` у TGStat привязан к IP+UA и протухает за часы. Куки
экспортируются с твоего браузера (твой IP) — на сервере IP другой, поэтому clearance не подойдёт и
прилетит challenge. Поэтому **TGStat на сервере выключен по умолчанию** (`ADSTAT_TGSTAT_ENABLED=false`).
Telemetr clearance не нужен — он работает с одной сессией. Включать TGStat на сервере только если на
серверном IP добывается свежий clearance (через [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)
или [CF-Clearance-Scraper](https://github.com/Xewdy444/CF-Clearance-Scraper)) и он дописывается в куки-файл.

## Куки
Экспортируй залогиненную сессию (Telemetr и/или TGStat) в формате **Netscape cookies.txt** (любое
браузерное расширение). Положи файл в секрет, путь — в `ADSTAT_COOKIES_PATH`. В репозиторий не коммить.
Когда сессия протухнет (Telemetr `PHPSESSID` живёт долго; TGStat clearance — часы) — переэкспортируй.

## Запуск
```bash
# локально/вручную, без записи в БД (печать JSON):
ADSTAT_COOKIES_PATH='/path/cookies.txt' python -m apps.worker.worker.adstat.run --dry-run kudago mscculture

# скрап указанных каналов с записью в adstat (нужен ADSTAT_ENABLED=true):
python -m apps.worker.worker.adstat.run kudago mscculture

# все активные adstat.targets → БД:
python -m apps.worker.worker.adstat.run
```
На сервере — через Prefect-флоу `scrape-adstat` (ежедневно, см. `prefect_serve.py`). Флоу безопасен в
расписании: при `ADSTAT_ENABLED=false` или отсутствии кук — no-op.

## Env (core/config/settings.py)
```
ADSTAT_ENABLED=false              # включить запись в БД (флоу/раннер)
ADSTAT_COOKIES_PATH=/app/secrets/adstat_cookies.txt
ADSTAT_TELEMETR_ENABLED=true
ADSTAT_TGSTAT_ENABLED=false       # см. оговорку про Cloudflare/IP
ADSTAT_DELAY_SEC=1.2              # пауза между запросами (бережём аккаунт от лимитов)
```

## Добавить каналы к сбору
```sql
INSERT INTO adstat.targets (username, city) VALUES
  ('kudago','Москва'), ('mscculture','Москва')
ON CONFLICT (username) DO NOTHING;
```

## Деплой
1. `git push` → на сервере `git pull`.
2. Миграция: `docker compose exec api alembic upgrade head` (создаст схему `adstat`).
3. Положить куки-файл по `ADSTAT_COOKIES_PATH`, выставить env, `ADSTAT_ENABLED=true`.
4. `docker compose restart prefect-serve` (подхватит флоу). Или разово: `docker compose exec prefect-serve python -m apps.worker.worker.adstat.run`.

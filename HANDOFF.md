# Окрест — handoff (лендинг / SEO / копирайтинг)

Краткая передача контекста для другого агента. Полная картина проекта — в авто-памяти
`~/.claude/projects/.../memory/MEMORY.md` (там 40+ заметок по бэку, дедупу, источникам, деплою и т.д.).
Этот файл — только про **последний пласт работы: маркетинговый лендинг и поисковую видимость.**

## Что за проект (в двух строках)
**Окрест** — Telegram mini-app «афиша событий на карте» для 16 городов России (~21 000 событий).
Монорепо: `miniapp/` (React+Vite+Leaflet/maplibre), `apps/api` (FastAPI), `landing/` (статический лендинг),
`infra/nginx/` (vhosts на хосте). Прод: l40s = `ubuntu@109.120.182.219`, код в `/var/www1/tg-bot-afisha`,
passwordless sudo, nginx **на хосте** (не в докере).

**Web-сплит:**
- `okrestmap.ru` — статический лендинг-визитка → `/var/www/okrest-landing/` (`index.html`, `og.png`, `robots.txt`, `sitemap.xml`, `favicon.svg`, `shots/*.jpg`).
- `app.okrestmap.ru` — гейтнутый SPA (Telegram-only, проксируется на Vite :5173).
- Конфиг: `infra/nginx/okrestmap.conf`.

## Что сделано за последнее время
1. **Живая карта в hero лендинга.** Настоящий Leaflet-инстанс (не скрин): CARTO `light_nolabels`,
   зафиксированный зум 4.5 (pan-only, без зума/кликов), 1:1 декоративный «хром» приложения (pill + ticker + banner,
   `pointer-events:none`), пины городов + созвездие MST + пульсации. Данные с `/v1/cities`. Leaflet грузится `defer`,
   карта инициализируется на `DOMContentLoaded` (чтобы не блокировать первую отрисовку).
2. **Реальные скрины приложения** для демо-блока. Гейт Telegram обходится локальным Playwright —
   тулинг в `C:\Users\Semyon\.okrest-shots\` (скрипты `landing-shot.js`, `seo-shot.js`, `verify-shot.js`, `og-render.js`).
   Способ обхода: `page.route` блокирует `telegram-web-app.js` + `addInitScript` подкладывает фейковый
   `window.Telegram.WebApp` (initData + platform=tdesktop) → гейт в `main.tsx` пропускает, публичная карта рендерится.
3. **SEO — техническая обвязка (готово, в проде):** `robots.txt`, `sitemap.xml`, `<link canonical>`, `robots`-мета,
   полный Open Graph + Twitter Card, `og.png` 1200×630 (брендовая карточка, генерится из `.okrest-shots/og.html`),
   JSON-LD `@graph` (Organization + WebSite + SoftwareApplication + **FAQPage**). Верификация подтверждена в
   **Яндекс.Вебмастере** (`yandex-verification 1080c2a501830974`) и **Google Search Console**
   (`google-site-verification vPrexlt72x3uw-UG8jdE1dETJbuHg49vNrrZMfgTBkY`) — мета-теги в `<head>`.
4. **SEO — on-page / контент:** секция «Уже работает в 16 городах» (чипы городов = ключи «афиша <город>»),
   FAQ-аккордеон (нативный `<details>`, текст в DOM для краулеров), title под «куда сходить».
5. **nginx-полировка:** лендинг отдаёт **реальный 404** на несуществующих путях (`try_files … =404`, было soft-404 200);
   `app.okrestmap.ru` помечен `X-Robots-Tag: noindex, nofollow` (гейтнутый SPA не должен индексироваться).
6. **Полный рерайт копирайтинга** (убрали «робота»): боль-первый заголовок «Хватит искать, куда сходить»,
   сценарная подача вместо повтора списка категорий (теперь категории звучат один раз в hero),
   параллельные карточки «На карте / В карточке / В списке», живые h2, человеческий FAQ
   («Окрест — это что?», «Это бесплатно? В чём подвох?», «Нужно что-то устанавливать?»).
   **Важно:** при правке FAQ синхронизируй видимый текст И `FAQPage`-схему (Google требует совпадения).

## Как деплоить
**Лендинг (статика):**
```bash
git add landing/... && git commit && git push origin main
ssh -o ControlMaster=no -o ControlPath=none -o ConnectTimeout=35 l40s \
  'cd /var/www1/tg-bot-afisha && git fetch -q origin && git reset --hard -q origin/main && \
   sudo cp /var/www1/tg-bot-afisha/landing/index.html /var/www/okrest-landing/index.html'
# + cp og.png/robots.txt/sitemap.xml/shots при изменении
```
**nginx:** `sudo cp infra/nginx/okrestmap.conf /etc/nginx/sites-available/okrestmap && sudo nginx -t && sudo systemctl reload nginx`
(sites-enabled/okrestmap — симлинк; reload graceful).
**App (SPA):** `docker compose restart miniapp` (Vite пересобирается ~9с).
**Проверка отдачи без DNS:** `curl -s --resolve okrestmap.ru:443:127.0.0.1 https://okrestmap.ru/...`
**JSON-LD валидация:** node-скрипт, который regex-достаёт `application/ld+json` и `JSON.parse` (см. историю).

## Что дальше (мои рекомендации)
1. **Off-page SEO — главный рычаг сейчас.** Техника и контент на потолке; позиции двигают ссылки и время.
   - Зарегистрировать `okrestmap.ru` в **Яндекс.Бизнес**, 2ГИС, тематических каталогах/афиша-агрегаторах.
   - Проставить ссылку на сайт в описании бота, Telegram-каналах, VK, соцсетях (брендовые запросы «окрест»).
2. **Внутри вебмастеров:** добавить `sitemap.xml` в обоих + отправить главную на переобход/переиндексацию
   (контента стало больше после копирайт-пасса). Через 1–2 недели проверить «Страницы в поиске» / «Покрытие».
3. **BotFather Mini App URL → `https://app.okrestmap.ru`** (давний хвост; проверить, что переключено).
4. **Заголовок hero — на развилке.** Стоит боль-первый «Хватит искать, куда сходить». Заготовлены альтернативы:
   «Рядом всегда что-то происходит» (бренд-поэтика, обыгрывает имя=рядом), «Город, в котором есть куда пойти».
   Можно A/B, если будет трафик.
5. **Мелочи лендинга (низкий приоритет):** `og:image:alt`, PNG/ico-фавикон для широкой совместимости.
6. **Тестировать бота/дайджест/напоминания ТОЛЬКО на @throlib** (telegram_user_id 5222335152, аккаунт владельца) —
   не гонять полный send-флоу, заденет реальных юзеров.

## Договорённости по стилю общения
Отвечать по-русски, заканчивать каждый ответ блоком «Итог». При дизайн-итерациях — делать сильный
вариант и показывать скрином, а не спрашивать «какой выбрать».

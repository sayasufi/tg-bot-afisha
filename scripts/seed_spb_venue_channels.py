"""Seed Saint Petersburg venue Telegram channels (2026-06-24). Each is an OFFICIAL single-venue
channel, fetch-verified via t.me/s/ during a research sweep. Same shape as the Moscow seed
(scripts/seed_venue_channels): probe t.me/s/<username> to drop dead handles, then INSERT the live
ones into ref.telegram_channels with city_id=3 (SPb) ON CONFLICT username DO NOTHING (re-run safe).

Run:  docker compose exec -T -e PYTHONPATH=/app prefect-serve python -m scripts.seed_spb_venue_channels
Dry:  ... python -m scripts.seed_spb_venue_channels --dry-run
"""
import asyncio
import sys

import httpx
from sqlalchemy import text

from core.db.session import WorkerAsyncSessionLocal

_CITY_ID = 3  # Saint Petersburg (ref.cities)

# (username, venue_name, venue_address) — None venue for multi-space clusters (LLM resolves per post).
CHANNELS: list[tuple[str, str | None, str | None]] = [
    # --- art spaces / cultural clusters / exhibition halls ---
    ("sevcableport", "Севкабель Порт", "Кожевенная линия 40"),
    ("newhollandsp", "Остров Новая Голландия", "набережная Адмиралтейского канала 2"),
    ("erarta_museum", "Музей современного искусства Эрарта", "29-я линия В.О. 2"),
    ("spbmanege", "ЦВЗ «Манеж»", "Исаакиевская площадь 1"),
    ("loftprojektetagi", "Лофт Проект Этажи", "Лиговский проспект 74"),
    ("thebertholdcentre", "Бертгольд Центр", "Гражданская улица 13-15"),
    ("thirdplaceru", "Третье место", "Литейный проспект 62"),
    ("nikolskiye", "Никольские ряды", "Садовая улица 62"),
    ("annenkirche", "Анненкирхе", "Кирочная улица 8В"),
    ("planetarium1", "Планетарий №1", "набережная Обводного канала 74Ц"),
    # --- concert halls / music venues ---
    ("kosmonavt_spb", "Клуб Космонавт", "Бронницкая улица 24"),
    ("aurora_concert", "Aurora Concert Hall", "Пироговская набережная 5/2"),
    ("domradio_online", "Дом Радио", "Итальянская улица 27"),
    ("capella_spb", "Государственная академическая капелла", "набережная реки Мойки 20"),
    ("philharmoniaspb", "Санкт-Петербургская филармония им. Шостаковича", "Михайловская улица 2"),
    # --- clubs / bars ---
    ("fishfabriquenouvelle", "Fish Fabrique Nouvelle", "Лиговский проспект 53"),
    ("serdcespb", "Сердце", "Лиговский проспект 50, корп. 16"),
    ("ionoteka_telegram", "Ионотека", "Лиговский проспект 50, корп. 16"),
    ("lastochka_leti", "Клуб Ласточка", "Транспортный переулок 10А"),
    # --- theatres ---
    ("mariinsky", "Мариинский театр", "Театральная площадь 1"),
    ("alexandrinsky", "Александринский театр", "площадь Островского 6"),
    ("bdtspb", "БДТ им. Г. А. Товстоногова", "набережная реки Фонтанки 65"),
    ("mikhailovskytheatre", "Михайловский театр", "площадь Искусств 1"),
    ("lensovet_theatre", "Театр им. Ленсовета", "Владимирский проспект 12"),
    ("mtfontanka", "Молодёжный театр на Фонтанке", "набережная реки Фонтанки 114"),
    ("spb_muzcomedy", "Театр музыкальной комедии", "Итальянская улица 13"),
    ("bolshoypuppet", "Большой театр кукол", "улица Некрасова 10"),
    ("baltichouse", "Театр-фестиваль «Балтийский дом»", "Александровский парк 4"),
    ("PloshadkaSkorohod", "Площадка «Скороход»", "Московский проспект 107, корп. 5"),
    # --- museums / galleries / circus ---
    ("hermitage_museum", "Государственный Эрмитаж", "Дворцовая площадь 2"),
    ("rusmuseum", "Государственный Русский музей", "Инженерная улица 4"),
    ("fabergemuseum", "Музей Фаберже", "набережная реки Фонтанки 21"),
    ("streetartmuseum", "Музей стрит-арта", "шоссе Революции 84"),
    ("bezbozarta", "KGallery", "набережная реки Фонтанки 24"),
    ("artschoolmasters", "Школа Masters", "набережная Адмирала Лазарева 24"),
    ("circusciniselli", "Большой Санкт-Петербургский цирк", "набережная реки Фонтанки 3"),
]


async def _probe(client: httpx.AsyncClient, username: str) -> str:
    try:
        r = await client.get(f"https://t.me/s/{username}")
    except httpx.HTTPError:
        return "ERR"
    if r.status_code in (404, 410):
        return "DEAD"
    if r.status_code != 200:
        return "EMPTY"
    return "OK" if "tgme_widget_message" in r.text else "EMPTY"


async def main(apply: bool) -> None:
    sem = asyncio.Semaphore(8)
    results: dict[str, str] = {}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0), follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
    ) as client:
        async def one(u: str) -> None:
            async with sem:
                results[u] = await _probe(client, u)
        await asyncio.gather(*(one(u) for u, _, _ in CHANNELS))

    by_status: dict[str, list[str]] = {}
    for u, st in results.items():
        by_status.setdefault(st, []).append(u)
    print("probe:", {k: len(v) for k, v in sorted(by_status.items())})
    if by_status.get("DEAD"):
        print("DEAD (dropped):", ", ".join(sorted(by_status["DEAD"])))
    if by_status.get("ERR"):
        print("ERR (kept, transient):", ", ".join(sorted(by_status["ERR"])))

    keep = [(u, n, a) for (u, n, a) in CHANNELS if results.get(u) != "DEAD"]
    added = skipped = 0
    async with WorkerAsyncSessionLocal() as db:
        for u, name, addr in keep:
            res = await db.execute(text(
                "insert into ref.telegram_channels (username, city_id, is_active, venue_name, venue_address) "
                "values (:u, :c, true, :n, :a) on conflict (username) do nothing"
            ), {"u": u, "c": _CITY_ID, "n": name, "a": addr})
            if res.rowcount:
                added += 1
            else:
                skipped += 1
        if apply:
            await db.commit()
        else:
            await db.rollback()
        spb = await db.scalar(text("select count(*) from ref.telegram_channels where is_active and city_id = :c"), {"c": _CITY_ID})
        total = await db.scalar(text("select count(*) from ref.telegram_channels where is_active"))
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: candidates={len(CHANNELS)} kept={len(keep)} added={added} skipped_existing={skipped} spb_active={spb} active_total={total}")


if __name__ == "__main__":
    asyncio.run(main(apply="--dry-run" not in sys.argv))

"""Seed venue Telegram channels for the million-plus cities (2026-06-24). Same shape as the Moscow/SPb
seeds (scripts/seed_venue_channels, scripts/seed_spb_venue_channels): probe t.me/s/<username> to drop
dead handles, then INSERT the live ones into ref.telegram_channels with the city's city_id, ON CONFLICT
(username) DO NOTHING (re-run safe). Each entry is an OFFICIAL single-venue channel, fetch-verified.

Run:  docker compose exec -T -e PYTHONPATH=/app prefect-serve python -m scripts.seed_city_venue_channels
Dry:  ... python -m scripts.seed_city_venue_channels --dry-run
"""
import asyncio
import sys

import httpx
from sqlalchemy import text

from core.db.session import WorkerAsyncSessionLocal

# ref.cities.city_id -> [(username, venue_name, address)]. None venue for multi-space clusters.
CHANNELS: dict[int, list[tuple[str, str | None, str | None]]] = {
    4: [  # Новосибирск
        ("novat_nsk", "Новосибирский театр оперы и балета (НОВАТ)", "Красный проспект, 36"),
        ("filnsk", "Новосибирская филармония (зал им. Каца)", "Красный проспект, 18/1"),
        ("theatre_globus", "Молодёжный театр «Глобус»", "ул. Каменская, 1"),
        ("red_torch", "Драмтеатр «Красный факел»", "ул. Ленина, 19"),
        ("teatr_oldhouse", "Драмтеатр «Старый дом»", "ул. Большевистская, 45"),
        ("puppetsnsk", "Новосибирский областной театр кукол", "ул. Ленина, 22"),
        ("muzkomnsk", "Новосибирский музыкальный театр", "ул. Каменская, 43"),
        ("teatrafanasieva", "Городской драмтеатр п/р С. Афанасьева", "ул. Максима Горького, 52"),
        ("first_teatre_nsk", "Молодёжный «Первый театр»", "ул. Чаплыгина, 36"),
        ("nebonsk", "Большой новосибирский планетарий", "ул. Ключ-Камышенское плато, 1/1"),
        ("circus_novosibirsk", "Новосибирский цирк", "ул. Челюскинцев, 21"),
        ("museum_for_people", "Новосибирский краеведческий музей", "Красный проспект, 23"),
        ("nghm_art", "Новосибирский художественный музей", "Красный проспект, 5"),
        ("RoerichN", "Музей Н. К. Рериха", "ул. Коммунистическая, 38"),
        ("m_nsk_ru", "Музей Новосибирска", "ул. Советская, 24"),
        ("cc19art", "Центр культуры ЦК19", "ул. Свердлова, 13"),
        ("Art_collezione", "Галерея «Частная коллекция»", "ул. Советская, 26"),
        ("death_museum", "Музей мировой погребальной культуры", "пос. Восход, ул. Военторговская, 4/15"),
        ("PodzemkaOfficial", "Лофт-парк «Подземка»", "Красный проспект, 161Б"),
        ("brodiachaia", "Кабаре-кафе «Бродячая собака»", "ул. Каменская, 32"),
        ("dkz_nsk", "ДК железнодорожников (ДКЖ)", "ул. Челюскинцев, 11"),
        ("dk_akademiya", "Дом культуры «Академия»", "ул. Ильича, 4"),
        ("dusoran", "Дом учёных СО РАН", "Морской проспект, 23"),
        ("revdk_kanal", "ДК им. Октябрьской революции", "ул. Ленина, 24"),
        ("vpobede", "Центр культуры «Победа»", "ул. Ленина, 7"),
        ("sibconcert", "Концертный зал «Евразия»", "ул. Селезнёва, 46"),
        ("domdavincingonb", "Арт-платформа «Дом да Винчи»", "ул. Коммунистическая, 34"),
    ],
    5: [  # Екатеринбург
        ("UralOperaBallet", "Урал Опера Балет (театр оперы и балета)", "проспект Ленина, 46"),
        ("kolyadateatr", "Коляда-Театр", "проспект Ленина, 97"),
        ("uraldrama", "Свердловский театр драмы", "Октябрьская площадь, 2"),
        ("muzkom_ekb", "Театр музыкальной комедии", "проспект Ленина, 47"),
        ("ekat_tuz_ves", "Екатеринбургский ТЮЗ", "ул. Карла Либкнехта, 48"),
        ("uralkukla", "Екатеринбургский театр кукол", "ул. Мамина-Сибиряка, 143"),
        ("csd_ekb", "Центр современной драматургии", "ул. Малышева, 145А"),
        ("volhonkateatr", "Театр «Волхонка»", "ул. Малышева, 21/1"),
        ("estradaural", "Уральский театр эстрады", "ул. 8 Марта, 15"),
        ("sgafme", "Свердловская филармония", "ул. Карла Либкнехта, 38А"),
        ("svobodaconcerthall", "Свобода Концерт Холл", "ул. Черкасская, 12"),
        ("jazz_club_everjazz", "Джаз-клуб EverJazz", "ул. Тургенева, 22"),
        ("nirvanaekb", "Клуб «Нирвана»", "ул. Шевченко, 9"),
        ("yeltsincenter", "Ельцин Центр", "ул. Бориса Ельцина, 3"),
        ("sinaracenter", "Синара Центр", "Верх-Исетский бульвар, 15/4"),
        ("glavprospekt", "Центр искусств «Главный проспект»", "проспект Ленина, 8"),
        ("domnaekb", "Креативный кластер «Домна»", "ул. Вайнера, 16"),
        ("domkinoekb", "Дом кино", "ул. Луначарского, 137"),
        ("ck_ural", "Культурный центр «Урал»", "ул. Студенческая, 3"),
        ("BelinkAnons", "Библиотека им. Белинского", "ул. Белинского, 15"),
        ("park_mayakovskogo", "ЦПКиО им. Маяковского", "ул. Мичурина, 230"),
        ("muzey_izo", "Музей изобразительных искусств (ЕМИИ)", "ул. Воеводина, 5"),
        ("SOKM_museum", "Свердловский краеведческий музей", "ул. Малышева, 46"),
        ("ekbmuseum1", "Музей истории Екатеринбурга", "ул. Карла Либкнехта, 26"),
        ("MuseumArchEkb", "Музей архитектуры и дизайна УрГАХУ", "ул. Горького, 4А"),
        ("ekbiconmuseum", "Музей «Невьянская икона»", "ул. Энгельса, 15"),
        ("ernstneizvestny", "Музей Эрнста Неизвестного", "ул. Добролюбова, 14"),
        ("museum_mikji", "Музей камнерезного и ювелирного искусства", "проспект Ленина, 37"),
        ("lit_kvartal", "Литературный квартал (Музей писателей Урала)", "ул. Пролетарская, 10"),
        ("dommetenkova", "Фотомузей «Дом Метенкова»", "ул. Тургенева, 15"),
    ],
    6: [  # Казань
        ("kazan_opera", "Театр оперы и балета им. Джалиля", "площадь Свободы, 2"),
        ("kamalteatr", "Театр им. Г. Камала", "ул. Хади Такташа, 74"),
        ("teatr_kachalova", "БДТ им. В. И. Качалова", "ул. Баумана, 48"),
        ("teatrtinchurin", "Театр драмы и комедии им. К. Тинчурина", "ул. Татарстан, 1"),
        ("kazantuz", "Казанский ТЮЗ", "ул. Островского, 10"),
        ("teatrkarieva", "Татарский ТЮЗ им. Г. Кариева", "ул. Петербургская, 55Б"),
        ("kazancircus", "Казанский цирк", "площадь Тысячелетия, 2"),
        ("monkazan", "Театральная площадка MOÑ", "ул. Пушкина, 86"),
        ("ugolkazan", "Творческая лаборатория «Угол»", "ул. Парижской Коммуны, 25/39"),
        ("kzn_kremlin", "Музей-заповедник «Казанский Кремль»", "Кремль"),
        ("tat_museum", "Национальный музей Республики Татарстан", "ул. Кремлёвская, 2"),
        ("musgirky_shalyapin", "Музей Горького и Шаляпина", "ул. Максима Горького, 10"),
        ("smena_kazan", "Центр современной культуры «Смена»", "ул. Бурхана Шахиди, 7"),
        ("werk_kazan", "Арт-пространство «Werk»", "ул. Габдуллы Тукая, 115, корп. 6"),
        ("solkzn", "Бар «Соль»", "ул. Профсоюзная, 22"),
        ("Alafuzov_loft", "Лофт «Фабрика Алафузова»", "ул. Гладилова, 55а"),
        ("millikitaphane", "Национальная библиотека Республики Татарстан", "ул. Пушкина, 86"),
        ("krkpyramida", "КРК «Пирамида»", "ул. Московская, 3"),
        ("gbkz_saydash", "Концертный зал им. С. Сайдашева", "площадь Свободы, 3"),
        ("kdklenin", "КДК им. В. И. Ленина", "ул. Копылова, 2а"),
        ("kazan_expo", "МВЦ «Казань Экспо»", "ул. Выставочная, 1, с. Большие Кабаны"),
        ("planetariumKazan", "Планетарий КФУ", "пос. Октябрьский, Зеленодольский р-н"),
        ("chakchakmuseum", "Музей чак-чака", "ул. Парижской Коммуны, 18А"),
        ("sovietlifestylemuseum", "Музей социалистического быта", "ул. Университетская, 9"),
        ("dom_nauki", "Дом занимательной науки", "ул. Габдуллы Тукая, 91"),
        ("kazanzoo1806", "Казанский зооботсад", "ул. Хади Такташа, 112"),
        ("kmcgru", "КМЦ им. А. Гайдара", "ул. Копылова, 7/2"),
    ],
}


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
    flat = [(cid, u, n, a) for cid, lst in CHANNELS.items() for (u, n, a) in lst]
    sem = asyncio.Semaphore(8)
    results: dict[str, str] = {}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0), follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
    ) as client:
        async def one(u: str) -> None:
            async with sem:
                results[u] = await _probe(client, u)
        await asyncio.gather(*(one(u) for (_c, u, _n, _a) in flat))

    by_status: dict[str, list[str]] = {}
    for u, st in results.items():
        by_status.setdefault(st, []).append(u)
    print("probe:", {k: len(v) for k, v in sorted(by_status.items())})
    if by_status.get("DEAD"):
        print("DEAD (dropped):", ", ".join(sorted(by_status["DEAD"])))
    if by_status.get("EMPTY"):
        print("EMPTY (kept — preview off / no posts yet):", ", ".join(sorted(by_status["EMPTY"])))
    if by_status.get("ERR"):
        print("ERR (kept, transient):", ", ".join(sorted(by_status["ERR"])))

    keep = [(c, u, n, a) for (c, u, n, a) in flat if results.get(u) != "DEAD"]
    added = skipped = 0
    async with WorkerAsyncSessionLocal() as db:
        for cid, u, name, addr in keep:
            res = await db.execute(text(
                "insert into ref.telegram_channels (username, city_id, is_active, venue_name, venue_address) "
                "values (:u, :c, true, :n, :a) on conflict (username) do nothing"
            ), {"u": u, "c": cid, "n": name, "a": addr})
            if res.rowcount:
                added += 1
            else:
                skipped += 1
        if apply:
            await db.commit()
        else:
            await db.rollback()
        per = (await db.execute(text(
            "select city_id, count(*) from ref.telegram_channels where is_active group by city_id order by city_id"
        ))).all()
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: candidates={len(flat)} kept={len(keep)} added={added} skipped_existing={skipped}")
    print("active channels per city_id:", [(r[0], r[1]) for r in per])


if __name__ == "__main__":
    asyncio.run(main(apply="--dry-run" not in sys.argv))

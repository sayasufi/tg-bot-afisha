"""One-off bulk seed of Moscow venue Telegram channels discovered via a parallel research sweep
(2026-06-24). Each entry is an OFFICIAL single-venue channel (clusters/promoters get NULL binding so
the LLM resolves the venue per post). The script first PROBES t.me/s/<username> to drop dead/typo
handles, then inserts the live ones into ref.telegram_channels (ON CONFLICT username DO NOTHING), so
re-running is safe. Telethon (the live connector) reads even web-preview-disabled channels, so an
EMPTY probe (reachable, preview off) is still inserted; only a 404/gone handle is dropped.

Run:  docker compose exec -T -e PYTHONPATH=/app prefect-serve python -m scripts.seed_venue_channels
Dry:  ... python -m scripts.seed_venue_channels --dry-run
"""
import asyncio
import sys

import httpx
from sqlalchemy import text

from core.db.session import WorkerAsyncSessionLocal

_CITY_ID = 1  # Moscow

# (username, venue_name, venue_address) — venue_name/address None for clusters & multi-space venues
# (the LLM then resolves each post's place). Addresses are research-grade hints; geocoding refines them.
CHANNELS: list[tuple[str, str | None, str | None]] = [
    # --- jazz / blues ---
    ("jamclubmoscow", "JAM Club", "Сретенка 11"),
    ("academ_jazz_club", "Академ Джаз Клуб", "Проспект Мира 26с1"),
    ("jao_da_official", "Китайский лётчик Джао Да", "Лубянский проезд 25с1"),
    ("louis_band", "Louis Jazz Club", "Спиридоньевский переулок 9/1"),
    ("papablues", "PAPA Blues Bar", "Староваганьковский переулок 19с3"),
    # --- rock / indie / metal / punk ---
    ("neuroticlub", "Невротик", "Яузская улица 5"),
    ("mo_yeti", "МО[ТРИ]", "Малая Семёновская 5с10"),
    ("ugolmsk", "Угол", "Новорязанская 29с4"),
    ("svobodaclub_msk", "Свобода", "Ленинградский проспект 47с19"),
    ("smenamoscow", "Смена", "Товарищеский переулок 4с5"),
    ("clubpravda_ru", "Pravda", "Варшавское шоссе 26с12"),
    ("RockNRollBarMoscow", "Rock'n'Roll bar", "Сретенка 11"),
    ("punkfictionbar", "Punk Fiction", "Ольховская 14с1"),
    ("tons16_arbat", "16 Тонн Арбат", "Арбат"),
    ("graphite_moscow", "Графит", "Электродная 2с32"),
    ("baseclubmsc", "Base", "Орджоникидзе 11"),
    ("tau_place", "TAU", "Рязанский проспект 8Ас10"),
    ("eclipse_clubmsk", "Eclipse", "Переведеновский переулок 21с7"),
    ("barbulldog", "Бульдог Бар", "Затонная 11к2А"),
    ("mtbarmoscow", "Мумий Тролль Music Bar", "Новый Арбат 24"),
    # --- electronic / techno / dance ---
    ("communitymoscow", "Community", "Космодамианская набережная 2"),
    ("pipl_life", "PIPL", "Комсомольская площадь 6"),
    ("fabula_gallery", "Fabula HQ", "Самокатная 4"),
    ("laski_club", "LASKI", "Рочдельская 15"),
    ("club_dex", "Dex", "Шарикоподшипниковская 13с32"),
    ("happyendmsc", "Happy End", "Спиридоньевский переулок"),
    ("bar_gipsy", "Gipsy", "Болотная набережная 3"),
    ("simach_telegram", "Simach", "Тверской бульвар 15"),
    ("stereo_people", "StereoPeople", "Новослободская 16А"),
    ("rovesnikbar", "Ровесник", "Малый Гнездниковский переулок 9с2"),
    ("treff8", "TREFF8", "Казакова 8с2"),
    ("rndmciub", "RNDM", "Наставнический переулок 13-15"),
    ("propagandamoscow", "Propaganda", "Большой Златоустинский переулок"),
    ("lachesis_groves", "Lachesis", "Чистопрудный бульвар 25"),
    ("npo_melody", "НПО Мелодия", "3-я улица Ямского Поля 2к5"),
    ("bounceclub", "Bounce", "3-я улица Ямского Поля 2к6"),
    ("strelkabarmoscow", "Strelka Bar", "Берсеневская набережная 14"),
    # --- standup / comedy / improv ---
    ("standupcafe", "StandUp Cafe", "Покровка 16"),
    ("StandupPatriki", "Stand Up Патрики", "Садовая-Кудринская 20"),
    ("COMEDY_34", "COMEDY 34", "Сретенка 34/1с1"),
    ("comedy_hub1", "Камеди Хаб", "Садовая-Черногрязская 22с1"),
    ("moscowimprovclub", "Moscow Improv Club", None),
    # --- theatres ---
    ("praktika_news", "Театр Практика", "Большой Козихинский переулок 30"),
    ("electrotheatrestanislavsky", "Электротеатр Станиславский", "Тверская 23"),
    ("Theatredoc", "Театр.doc", "Лесная 59с1"),
    ("fomenkiru", "Мастерская Петра Фоменко", "Набережная Тараса Шевченко 29"),
    ("bpstd", "Боярские палаты СТД", "Страстной бульвар 10"),
    ("tofnations", "Театр Наций", "Петровский переулок 3"),
    ("sovremenniktheatre", "Современник", "Чистопрудный бульвар 19"),
    ("mxatchekhova", "МХТ им. Чехова", "Камергерский переулок 3"),
    ("theatre_etcetera", "Театр Et Cetera", "Фролов переулок 2"),
    ("sdart_19", "Школа драматического искусства", "Сретенка 19"),
    ("teatrsti", "Студия театрального искусства", "Улица Станиславского 21"),
    ("tagankatheatre", "Театр на Таганке", "Земляной Вал 76/21"),
    ("ramteatr", "РАМТ", "Театральная площадь 2"),
    ("Satirikon_theatre", "Сатирикон", "Шереметьевская 8"),
    ("teatr_mayakovskogo", "Театр им. Маяковского", "Большая Никитская 19/13"),
    ("teatrlenkom", "Ленком", "Малая Дмитровка 6"),
    ("teatrpushkin", "Театр им. Пушкина", "Тверской бульвар 23"),
    ("ermistage", "Театр Эрмитаж", "Новый Арбат 11"),
    ("neglinka29", "Школа современной пьесы", "Неглинная 29/14"),
    ("okolotheatre", "Театр ОКОЛО", "Вознесенский переулок 9с1"),
    ("o3epotheatre", "Театр Озеро", None),
    ("teatr_sreda21", "Театр Среда 21", "Старая Басманная 21/4"),
    ("kstatiteatr", "Кстати театр", "Георгиевский переулок 3с3"),
    ("theatreatelier", "Театр Ателье", "Сретенский бульвар"),
    ("shalomteatr", "Театр Шалом", "Варшавское шоссе 71к1"),
    ("spheratheatre", "Театр Сфера", "Каретный Ряд 3с1"),
    ("teatrmost", "Театр МОСТ", "Большая Садовая 6"),
    ("teakam", "Театр музыки и поэзии Елены Камбуровой", "Большая Пироговская 53/55"),
    ("teatrnadoskah", "Театр На досках", "Садовая-Кудринская 25"),
    ("vnutri_space", "Пространство Внутри", "Казакова 8с3"),
    # --- concert halls ---
    ("vk_stadium", "VK Stadium", "Ленинградский проспект 80к17"),
    ("tkz_cdkg", "ЦДКЖ", "Комсомольская площадь 4"),
    ("YauzaPalace", "Дворец на Яузе", "Площадь Журавлёва 1"),
    ("concert_hall_moscow", "Концертный зал Москва", "Проспект Андропова 1"),
    ("dkrassvet", "ДК Рассвет", "Столярный переулок 3к15"),
    ("dommuzyki", "Московский международный Дом музыки", "Космодамианская набережная 52с8"),
    ("moscowteatrestrady", "Московский театр Эстрады", "Берсеневская набережная 20/2"),
    # --- museums / galleries ---
    ("vacges2", "Дом культуры ГЭС-2", "Болотная набережная 15"),
    ("garagemca", "Музей «Гараж»", "Крымский Вал 9с32"),
    ("multimediaartmuseum", "Мультимедиа Арт Музей", "Остоженка 16"),
    ("jewishmuseum", "Еврейский музей и центр толерантности", "Образцова 11с1А"),
    ("mosmuseum", "Музей Москвы", "Зубовский бульвар 2"),
    ("centrezotov", "Центр «Зотов»", "Ходынская 2с1"),
    ("mmoma", "Московский музей современного искусства", "Петровка 25"),
    ("voznesenskycenter", "Центр Вознесенского", "Большая Ордынка 46с3"),
    ("cube_moscow", "Cube.Moscow", "Тверская 3"),
    ("ruartsfoundation", "Фонд Ruarts", "Трубниковский переулок 6"),
    ("azmuseum", "Музей AZ", "2-я Тверская-Ямская 20-22"),
    ("triumphgallery", "Галерея «Триумф»", "Ильинка 3/8с5"),
    ("pop_off_art", "pop/off/art", "4-й Сыромятнический переулок 1с6"),
    ("astraartgallery", "a-s-t-r-a Gallery", "4-й Сыромятнический переулок 1с6"),
    ("bisartgallery", "BIS ART", "4-й Сыромятнический переулок 1с6"),
    ("pennlab", "PENNLAB Gallery", "4-й Сыромятнический переулок 1с6"),
    ("vladeygram", "VLADEY", "4-й Сыромятнический переулок 1с6"),
    ("szenagallery", "Галерея сцена/szena", "Пятницкая 42"),
    ("postrigay_gallery", "Postrigay Gallery", "Тверская 3"),
    ("na_shabolovke", "Галерея на Шаболовке", "Серпуховский Вал 24к2"),
    ("GT_Gallery", "Третьяковская галерея", "Крымский Вал 10"),
    ("theartsmuseum", "ГМИИ им. Пушкина", "Волхонка 12"),
    ("state_historical_museum", "Государственный исторический музей", "Красная площадь 1"),
    ("rusimp_museum", "Музей русского импрессионизма", "Ленинградский проспект 15с11"),
    ("polytechmuseum", "Политехнический музей", "Новая площадь 3/4"),
    ("statedarwinmuseum", "Дарвиновский музей", "Вавилова 57"),
    ("kosmo_museum", "Музей космонавтики", "Проспект Мира 111"),
    ("biomuseum", "Биологический музей им. Тимирязева", "Малая Грузинская 15"),
    ("orientmuseum", "Музей Востока", "Никитский бульвар 12А"),
    ("pushkin_museum", "Музей А.С. Пушкина", "Пречистенка 12/2"),
    ("ekaterinafoundation", "Фонд культуры «Екатерина»", "Кузнецкий Мост 21/5"),
    ("lumiere_gallery", "Центр фотографии им. братьев Люмьер", "Болотная набережная 3с1"),
    ("bakhrushinmuseum", "Бахрушинский театральный музей", "Улица Бахрушина 31/12"),
    ("musnaive", "Музей русского лубка и наивного искусства", "Сретенский тупик 10А"),
    ("VZbelyaevo_gallery", "Галерея «Беляево»", "Профсоюзная 100"),
    ("musicmuseum_ru", "Музей музыки", "Фадеева 4"),
    ("scriabinmuseum", "Музей А.Н. Скрябина", "Большой Николопесковский переулок 11"),
    ("tsvetaevamuseum", "Дом-музей Марины Цветаевой", "Борисоглебский переулок 6"),
    ("domrz", "Дом русского зарубежья им. Солженицына", "Нижняя Радищевская 2"),
    ("bulgakovmuseum", "Музей М.А. Булгакова", "Большая Садовая 10"),
    ("richter_hotel", "Рихтер", "Пятницкая 42"),
    ("artcenter_mars", "Центр М'АРС", "Пушкарёв переулок 5"),
    ("cca_winzavod", "Винзавод", "4-й Сыромятнический переулок 1"),
    ("cci_fabrika", "ЦТИ «Фабрика»", "Переведеновский переулок 18"),
    ("cosmos_vdnh", "Павильон «Космос» ВДНХ", "Проспект Мира 119"),
    # --- creative clusters / lofts (NULL binding — multi-space, LLM resolves per post) ---
    ("Hlebozavod9", None, None),
    ("dezignzavod", None, None),
    ("Artplay_mos", None, None),
    ("supermetall", None, None),
    ("depomos", None, None),
    ("trivokzaladepo", None, None),
    ("ile_theleme", "Île Thélème", "Улица Правды 24с3"),
    ("vnutricenter", "Центр Внутри", "Новодмитровская 1с4"),
    ("bbbmsk", "Bla Bla Bar", "Лесная 20с5"),
    ("drunkyourself", "Рюмочная №9", "Новодмитровская 1с27"),
    ("urbn_live", "Урбан", "Большая Новодмитровская 36"),
    ("britankamedia", "Британская высшая школа дизайна", "Нижняя Сыромятническая 10"),
    ("screamschool", "Scream School", "Нижняя Сыромятническая 10"),
    ("moscowfilmschool", "Московская школа кино", "Нижняя Сыромятническая 10"),
    # --- cultural centres / houses of culture ---
    ("zilcc_official", "Культурный центр ЗИЛ", "Восточная 4к1"),
    ("pokrovka27", "Культурный центр «Покровские ворота»", "Покровка 27с1"),
    ("mskcctg", "Культурный центр «Москвич»", "Волгоградский проспект 46/15"),
    ("vdohnovenie_cc", "Культурный центр «Вдохновение»", "Литовский бульвар 7"),
    ("meridiancentre", "Культурный центр «Меридиан»", "Профсоюзная 61"),
    ("hitrovka_center", "Культурный центр «Хитровка»", "Подколокольный переулок 8"),
    ("ccvnukovo", "Культурный центр «Внуково»", "Большая Внуковская 6"),
    ("kcsalut", "Культурный центр «Салют»", "Свободы 37"),
    ("arhecenter", "Культурно-просветительский центр «Архэ»", "Дубининская 20с2"),
    ("domgogolya", "Дом Гоголя", "Никитский бульвар 7А"),
    ("dknekrasovka", "Культурный центр «Заречье»", None),
    ("dktemp", "Дом культуры «Тёмп»", "Шенкурский проезд 3Б"),
    ("kczagorie", "Дом культуры «Загорье»", "Лебедянская 24/2"),
    ("biblioteka157", "Культурный центр «Маяк»", "Газопровод 9А"),
    ("gaidarovec", "Дом культуры «Гайдаровец»", "Земляной Вал 27с2"),
    ("pperedelkino", "Дом творчества Переделкино", "Погодина 4"),
    # --- libraries with event programs ---
    ("turgenevka", "Тургеневская библиотека", "Бобров переулок 6с1"),
    ("nekrasovkalibrary", "Библиотека им. Некрасова", "Бауманская 58/25к14"),
    ("domloseva", "Дом А.Ф. Лосева", "Арбат 33"),
    ("rgubru", "Российская государственная библиотека для молодёжи", "Большая Черкизовская 4к1"),
    ("svetlovkamoscow", "Библиотека им. Светлова", "Большая Садовая 1"),
    ("bibliogriboedov", "Библиотека им. Грибоедова", "Большая Переяславская 15"),
    ("libfl", "Библиотека иностранной литературы", "Николоямская 1"),
    ("leninka_ru", "Российская государственная библиотека", "Воздвиженка 3/5"),
    ("gaidarovka", "ЦГДБ им. Гайдара", "3-я Фрунзенская 9"),
    # --- parks with event programs (NULL address — large; LLM resolves stage per post) ---
    ("zaryadye_official", "Парк «Зарядье»", "Улица Варварка 6"),
    ("gorkyparkmsk", "Парк Горького", "Крымский Вал 9"),
    ("parksokolniki", "Парк «Сокольники»", "Сокольнический Вал 1с1"),
    ("park_fili", "Парк «Фили»", "Большая Филёвская 22"),
    ("kuzminki_lublino", "Музей-заповедник «Кузьминки-Люблино»", "Тополевая аллея 6"),
    ("vdnh_moscow", "ВДНХ", "Проспект Мира 119"),
    ("parktaganskiy", "Таганский парк", "Таганская 40/42"),
    ("mosgorsad", "Сад «Эрмитаж»", "Каретный Ряд 3"),
    ("sadbaumana", "Сад имени Баумана", "Старая Басманная 15А с4"),
    # --- chamber / classical / organ / folk / bard / live bars ---
    ("zaryadyehall", "Концертный зал «Зарядье»", "Улица Варварка 6с4"),
    ("mosfilarmonia", "Московская филармония", "Триумфальная площадь 4/31"),
    ("mosconsv", "Московская консерватория", "Большая Никитская 13/6"),
    ("gnesinacademy", "Российская академия музыки им. Гнесиных", "Поварская 30-36"),
    ("lihov6", "Соборная палата", "Лихов переулок 6с1"),
    ("kuskovo_museum", "Музей-усадьба «Кусково»", "Улица Юности 2"),
    ("ostankino_museum", "Музей-усадьба «Останкино»", "1-я Останкинская 5"),
    ("VisotskyMuseum", "Дом Высоцкого на Таганке", "Нижний Таганский тупик 3"),
    ("kinoklub_eldar", "Киноконцертный зал «Эльдар»", "Ленинский проспект 105"),
    ("cafekv44", "Квартира 44", "Малая Ордынка 24"),
    ("petterbar", "PETTER", "Петровка 21с1"),
    ("dompoetov8", "Дом поэтов", "Трёхпрудный переулок 8"),
]


async def _probe(client: httpx.AsyncClient, username: str) -> str:
    """Classify the channel: OK (public, has posts), EMPTY (reachable, preview off / no posts — still
    Telethon-readable so we keep it), DEAD (404/gone — drop)."""
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

    # Keep everything except DEAD (Telethon reads preview-off channels; ERR is transient network).
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
        total = await db.scalar(text("select count(*) from ref.telegram_channels where is_active"))
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: candidates={len(CHANNELS)} kept={len(keep)} added={added} skipped_existing={skipped} active_total={total}")


if __name__ == "__main__":
    asyncio.run(main(apply="--dry-run" not in sys.argv))

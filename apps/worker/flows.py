"""Prefect flows — the orchestration layer that replaced Celery.

Each flow is a thin wrapper around an existing task implementation (the proven
``_*_impl`` functions); Prefect handles scheduling, retries, concurrency and the
run history/observability UI. The logic lives in ``tasks/*`` and is unchanged.
"""
from prefect import flow

from apps.worker.tasks import broadcasts, dedup, digest, enrich, fetch, media, normalize, reminders, search_index

_RETRIES = 2
_RETRY_DELAY = 30  # seconds


# --- adstat (рекламный ресёрч каналов) ---------------------------------------

@flow(name="scrape-adstat", retries=1, retry_delay_seconds=120, timeout_seconds=5400, log_prints=True)
async def scrape_adstat():
    """Daily: лёгкий рефреш статистики — ТОЛЬКО Telemetr, и НЕ все ~6000 таргетов за раз (это упиралось
    в таймаут 60м), а срез из 800 самых несвежих (по last_scraped_at) — полный охват ротируется за ~8 дней.
    No-op при ADSTAT_ENABLED=false."""
    import asyncio

    from apps.adstat.service import scrape

    rows = await asyncio.to_thread(scrape, None, False, ["telemetr"], 800)
    ok = sum(1 for r in rows if not r.get("error"))
    return {"rows": len(rows), "ok": ok}


@flow(name="discover-adstat", retries=1, retry_delay_seconds=300, timeout_seconds=3600, log_prints=True)
async def discover_adstat():
    """Daily: автопоиск новых афиша-каналов (Telemetr search по 16 городам) → targets + снимки."""
    import asyncio

    from apps.adstat.discover import discover

    rows = await asyncio.to_thread(discover, 3000, False)
    return {"found": len(rows)}


@flow(name="discover-telethon", retries=1, retry_delay_seconds=300, timeout_seconds=5400, log_prints=True)
async def discover_telethon_flow():
    """Daily: расширить афиша-граф через рекомендации Telegram (Telethon, бесплатно) + метрики → adstat."""
    import asyncio

    from apps.adstat.telethon_src import discover_telethon

    n = await asyncio.to_thread(discover_telethon, None, 1000, False)
    return {"written": n}


@flow(name="discover-telega", retries=1, retry_delay_seconds=300, timeout_seconds=5400, log_prints=True)
async def discover_telega_flow():
    """Daily: каталог афиша-категории Telega.in (тысячи каналов) + реальные цены размещения → adstat."""
    import asyncio

    from apps.adstat.discover import discover_telega

    # 200 стр. каталога (из ~749) БЕЗ цен — быстро, ловит куда больше каналов (60 стр. оставляли каталог
    # почти нетронутым: 60→150 стр. дало +3114). Цены НЕ тянем на тысячи каналов ежедневно (это per-card
    # HTTP) — их добираем точечно для шорт-листа топ-каналов на этапе скоринга.
    rows = await asyncio.to_thread(discover_telega, 52, 200, False, False)
    return {"found": len(rows)}


@flow(name="enrich-shortlist-prices", retries=1, retry_delay_seconds=120, timeout_seconds=1800, log_prints=True)
async def enrich_shortlist_prices_flow():
    """Daily: добрать реальные цены telega по топ-АФИША каналам без CPM → CPM завершается → проходят в «брать».
    Цены точечно по шорт-листу (не на тысячи каналов ежедневно — это per-card HTTP)."""
    import asyncio

    from apps.adstat.discover import enrich_shortlist_prices

    n = await asyncio.to_thread(enrich_shortlist_prices, 60, False)
    return {"priced": n}


# --- fetch (sources) ---------------------------------------------------------

@flow(name="fetch-kudago", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_kudago():
    return await fetch._fetch_kudago_impl()


@flow(name="fetch-kudago-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_kudago_full_scan():
    return await fetch._fetch_kudago_full_scan_impl()


@flow(name="fetch-yandex-afisha", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_yandex_afisha():
    return await fetch._fetch_yandex_impl()


@flow(name="fetch-yandex-afisha-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_yandex_afisha_full_scan():
    return await fetch._fetch_yandex_full_scan_impl()


@flow(name="fetch-afisha-ru", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_afisha_ru():
    return await fetch._fetch_afisha_impl()


@flow(name="fetch-afisha-ru-full-scan", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_afisha_ru_full_scan():
    return await fetch._fetch_afisha_full_scan_impl()


@flow(name="fetch-timepad", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_timepad():
    return await fetch._fetch_timepad_impl()


@flow(name="fetch-telegram-public", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1800, log_prints=True)
async def fetch_telegram_public():
    return await fetch._fetch_telegram_impl()


@flow(name="prune-telegram-channels", retries=1, retry_delay_seconds=60, timeout_seconds=600, log_prints=True)
async def prune_telegram_channels():
    """Daily: deactivate channels that went dark (no posts in 60d / preview gone) AND channels that proved
    NOT to be event sources (fetched long enough, posts processed, but 0 events) so the active set stays live."""
    from pipeline.maintenance.telegram_health import prune_stale_channels, retire_zero_yield_channels
    dark = await prune_stale_channels()
    zero_yield = await retire_zero_yield_channels()
    return {**dark, **zero_yield}


@flow(name="sweep-orphan-concurrency", retries=1, retry_delay_seconds=30, timeout_seconds=120, log_prints=True)
def sweep_orphan_concurrency_slots():
    """Self-heal the Prefect runner. A flow run that crashed / was killed (deploy, OOM, restart) without
    cleanly releasing its deployment concurrency slot leaves concurrency_limit_v2.active_slots STUCK at the
    limit → that deployment is wedged forever (the runner aborts every submission as 'non-pending SCHEDULED').
    This is why daily/12h flows silently stopped running for days. Every 30 min: release any slot 'occupied'
    with no actual PENDING/RUNNING run, and collapse the overdue SCHEDULED pile-up (keep only the latest
    pending run per deployment) so a backlog never drowns the runner. Operates on the prefect-postgres store."""
    import os

    from sqlalchemy import create_engine, text

    url = (os.environ.get("PREFECT_API_DATABASE_CONNECTION_URL") or "").replace("+asyncpg", "+psycopg")
    if not url:
        pw = os.environ.get("PREFECT_DB_PASSWORD")  # the runner reaches the API, not the DB — build from .env
        if pw:
            url = f"postgresql+psycopg://prefect:{pw}@prefect-postgres:5432/prefect"
    if not url:
        return {"skipped": "no prefect db url"}
    eng = create_engine(url, pool_pre_ping=True)
    try:
        with eng.begin() as c:
            # 1) Kill ZOMBIE running runs first. A run RUNNING longer than the LONGEST flow timeout (the adstat
            #    flows are 5400s = 90 min) is dead — its process was hard-killed (OOM/SIGKILL) so Prefect never
            #    finalised it; the record lingers AND makes its slot look held. 2h is safely past every timeout
            #    (so a legit 90-min run is NOT killed). MUST run before the slot release, else the zombie's own
            #    RUNNING row blocks that slot from freeing. (Restart-orphans are cleared eagerly at startup.)
            zombies = c.execute(text(
                "DELETE FROM flow_run WHERE state_type = 'RUNNING' AND start_time < now() - interval '2 hours'"
            )).rowcount
            # 2) Release any deployment slot NOT held by a FRESH (pending, or running <2h) run — frees slots
            #    orphaned by a kill or by the zombies just deleted. <2h matches the kill threshold so a legit
            #    long run's slot is never released out from under it.
            released = c.execute(text(
                "UPDATE concurrency_limit_v2 clv SET active_slots = 0 "
                "WHERE clv.active_slots > 0 AND clv.name LIKE 'deployment:%' "
                "  AND NOT EXISTS (SELECT 1 FROM flow_run fr WHERE ('deployment:' || fr.deployment_id::text) = clv.name "
                "    AND (fr.state_type = 'PENDING' "
                "         OR (fr.state_type = 'RUNNING' AND fr.start_time > now() - interval '2 hours')))"
            )).rowcount
            # 3) Collapse the overdue SCHEDULED pile-up: keep only the LATEST pending run per deployment.
            collapsed = c.execute(text(
                "DELETE FROM flow_run fr WHERE fr.state_type = 'SCHEDULED' AND fr.deployment_id IS NOT NULL "
                "  AND EXISTS (SELECT 1 FROM flow_run fr2 WHERE fr2.deployment_id = fr.deployment_id "
                "              AND fr2.state_type = 'SCHEDULED' AND fr2.expected_start_time > fr.expected_start_time)"
            )).rowcount
    finally:
        eng.dispose()
    if zombies or released or collapsed:
        print(f"sweep-orphan-concurrency: killed {zombies} zombie runs, released {released} slots, collapsed {collapsed} scheduled")
    return {"killed_zombies": zombies, "released_slots": released, "collapsed_scheduled": collapsed}


@flow(name="sweep-stale-runs", retries=1, retry_delay_seconds=30, timeout_seconds=120, log_prints=True)
async def sweep_stale_runs():
    """Mark source_runs stuck in 'running' (a fetch orphaned by a deploy/crash between create_source_run
    and finish_source_run) as 'interrupted', so the run log doesn't fill with phantom in-flight rows."""
    from core.db.repositories.ingestion import sweep_stale_source_runs
    from core.db.session import WorkerAsyncSessionLocal
    async with WorkerAsyncSessionLocal() as db:
        return await sweep_stale_source_runs(db)


@flow(name="refresh-channel-subscribers", retries=1, retry_delay_seconds=60, timeout_seconds=600, log_prints=True)
async def refresh_channel_subscribers():
    """Daily: cache each active telegram channel's subscriber count (reach signal) from its t.me page."""
    from pipeline.maintenance.telegram_health import refresh_subscribers
    return await refresh_subscribers()


@flow(name="reindex-search", retries=1, retry_delay_seconds=30, timeout_seconds=600, log_prints=True)
async def reindex_search():
    """Refresh the Meilisearch typeahead index from active events (no-op when search is disabled)."""
    return await search_index._reindex_search_impl()


# --- pipeline (normalize -> enrich -> dedup) ---------------------------------

@flow(name="normalize-raw", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def normalize_raw():
    return await normalize._normalize_impl()


@flow(name="retry-transient-skips", retries=1, retry_delay_seconds=60, timeout_seconds=300, log_prints=True)
def retry_transient_skips():
    """Переоткрыть raw_events с ТРАНЗИЕНТНЫМ LLM-skip (llm_error/invalid_json) → попадут обратно в очередь
    нормализации; счётчик llm_attempts++, после 5 попыток — терминальный 'llm_error_dead'. Чинит
    безвозвратную потерю TG-событий в окно недоступности LLM (unprocessed_raw_ids берёт только skip_reason='')."""
    from sqlalchemy import text

    from core.db.session import SessionLocal
    with SessionLocal() as db:
        dead = db.execute(text(
            "UPDATE events.raw_events SET skip_reason='llm_error_dead' "
            "WHERE skip_reason IN ('llm_error','invalid_json') AND llm_attempts >= 5"
        )).rowcount
        # Переоткрываем ПАЧКОЙ (новейшие первыми), а не всё разом: при многочасовом простое LLM накапливаются
        # тысячи llm_error, и одномоментный reopen затопил бы общий llm_slot-бюджет, вытеснив свежий ингест и
        # массово докрутив llm_attempts к терминалу. LIMIT 500/цикл (раз в 30 мин) растекает ретраи по времени;
        # непопавшие остаются с llm_error (llm_attempts НЕ инкрементится зря) и подхватятся следующим прогоном.
        reopened = db.execute(text(
            "UPDATE events.raw_events SET skip_reason='', llm_attempts=llm_attempts+1 "
            "WHERE raw_id IN (SELECT raw_id FROM events.raw_events "
            "  WHERE skip_reason IN ('llm_error','invalid_json') AND llm_attempts < 5 "
            "  ORDER BY raw_id DESC LIMIT 500)"
        )).rowcount
        db.commit()
    return {"reopened": reopened, "dead": dead}


@flow(name="source-freshness-watch", retries=0, timeout_seconds=120, log_prints=True)
async def source_freshness_watch():
    """Алерт владельцу, если КОННЕКТОР (yandex/afisha/kudago/timepad/telegram) перестал УСПЕШНО собирать
    события > N часов — «тихая смерть» источника (смена схемы/captcha/дохлый токен) иначе видна только
    вручную в админке. Группируем 376 sources в коннекторы по имени; throttle — раз в день на коннектор."""
    from datetime import datetime, timezone

    import httpx
    from sqlalchemy import text

    from core.config.settings import get_settings
    from core.db.session import WorkerAsyncSessionLocal
    from core.infra.redis import get_redis

    # Часть коннекторов (yandex/afisha/telegram) — ЕЖЕСУТОЧНЫЕ, плюс рестарт prefect-serve сбрасывает таймер
    # interval-флоу. Поэтому порог щедрый: алерт только если коннектор не собирал успешно >30ч (пропустил
    # более чем суточный цикл = реально мёртв), а не «бежит чуть позже».
    STALE_H = 30
    settings = get_settings()
    owner = settings.admin_test_user_id or 5222335152  # владелец сервиса (@throlib)
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT CASE WHEN s.kind = 'telegram' THEN 'telegram' ELSE substring(s.name from '^[a-z]+') END AS conn, "
            "  count(DISTINCT s.source_id) AS srcs, max(r.finished_at) AS last_ok "
            "FROM ref.sources s "
            "LEFT JOIN events.source_runs r ON r.source_id = s.source_id AND r.status = 'success' "
            "  AND r.finished_at > now() - interval '2 days' "
            # user_submission-<city> sources are WRITE-TIME containers (raw_events written on admin approve),
            # NOT fetched connectors — they never have a source_run, so exclude them or they always false-alarm.
            "WHERE s.is_active AND s.kind <> 'user_submission' GROUP BY 1"
        ))).all()
    now = datetime.now(timezone.utc)
    stale = []
    for conn, srcs, last_ok in rows:
        if not conn:
            continue
        age_h = None if last_ok is None else (now - last_ok).total_seconds() / 3600
        if age_h is None or age_h > STALE_H:
            stale.append((conn, int(srcs or 0), "никогда(>2д)" if age_h is None else f"{int(age_h)}ч"))
    if not stale or not settings.telegram_bot_token:
        return {"stale": [s[0] for s in stale], "notified": False}
    client = get_redis(decode=True)
    day = now.strftime("%Y%m%d")
    lines = []
    for conn, srcs, age in stale:
        send = True
        if client is not None:
            try:
                send = bool(await client.set(f"srcwatch:{conn}:{day}", "1", nx=True, ex=2 * 24 * 3600))
            except Exception:
                send = True
        if send:
            lines.append(f"• <b>{conn}</b> — нет успешного сбора {age} ({srcs} ист.)")
    if not lines:
        return {"stale": [s[0] for s in stale], "notified": False}
    msg = "⚠️ <b>Источники молчат</b>\n\n" + "\n".join(lines) + "\n\nПроверь коннектор/токен/схему (Админка → Источники)."
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                         json={"chat_id": int(owner), "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True})
    except Exception:
        pass
    return {"stale": [s[0] for s in stale], "notified": True}


@flow(name="submissions-status-watch", retries=0, timeout_seconds=120, log_prints=True)
async def submissions_status_watch():
    """Close the loop on APPROVED user submissions: advance to a terminal state + DM the submitter.
    Nothing should hang in 'approved'. Signals:
      • EVENT ingested → a row in events.event_sources for target_raw_id (dedup wrote the event↔raw link)
        → 'ingested' + «уже на карте: <deep-link>».
      • EVENT failed → the raw got a terminal skip_reason (not-an-event/past), OR its candidate stayed
        venue_id NULL >2h (address ungeocodable), OR nothing after 24h → 'failed' + honest DM.
      • CHANNEL ingested → a successful source_run for telegram_public:<username> (the channel was read)
        → 'ingested' + «канал подключён»."""
    from datetime import datetime, timedelta, timezone

    import httpx
    from sqlalchemy import text

    from core.config.settings import get_settings
    from core.db.session import WorkerAsyncSessionLocal
    from core.render.formatting import ce, event_deeplink

    token = get_settings().telegram_bot_token

    async def _dm(uid, body: str) -> None:
        if not token or not uid:
            return
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                await c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": int(uid), "text": body, "parse_mode": "HTML",
                                   "disable_web_page_preview": True})
        except Exception:
            pass

    ingested = failed = 0
    now = datetime.now(timezone.utc)
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT submission_id, kind, submitted_by, data, target_raw_id, reviewed_at "
            "FROM ref.pending_submissions WHERE status = 'approved' ORDER BY created_at LIMIT 500"
        ))).mappings().all()
        for r in rows:
            sid, kind, uid = r["submission_id"], r["kind"], r["submitted_by"]
            data = r["data"] or {}
            if kind == "event":
                rid = r["target_raw_id"]
                if not rid:
                    continue
                es = (await db.execute(
                    text("SELECT event_id FROM events.event_sources WHERE raw_id = :r LIMIT 1"), {"r": rid}
                )).first()
                if es:
                    eid = str(es[0])
                    await db.execute(text(
                        "UPDATE ref.pending_submissions SET status='ingested', "
                        "target_event_id = CAST(:e AS uuid), updated_at = now() WHERE submission_id = :s"
                    ), {"e": eid, "s": sid})
                    await db.commit()
                    ingested += 1
                    await _dm(uid, f"{ce('✨')} <b>Готово!</b> Твоё событие уже на карте — "
                                   f"<a href=\"{event_deeplink(eid)}\">открыть</a>. Спасибо!")
                    continue
                skip = (await db.execute(
                    text("SELECT skip_reason FROM events.raw_events WHERE raw_id = :r"), {"r": rid}
                )).scalar()
                # Failure signals (NO venue_id-NULL geo-fail check: enrich always sets venue_id — a real
                # geocode failure still yields a geom-less venue + an event, so it goes 'ingested'; venue_id
                # NULL only means «enrich hasn't run yet», which during a backlog would false-fail a valid
                # event). Backstop anchors on reviewed_at (APPROVAL time), not created_at — else a submission
                # moderated >24h after submit is failed instantly before the pipeline even runs.
                reviewed = r["reviewed_at"]
                reason = None
                if skip and skip not in ("llm_error", "invalid_json"):  # transient skips still retry
                    reason = "не удалось распознать событие"
                elif reviewed and reviewed < now - timedelta(hours=48):  # genuinely stuck 48h after approval
                    reason = "не удалось разместить событие"
                if reason:
                    await db.execute(text(
                        "UPDATE ref.pending_submissions SET status='failed', reject_code='ingest_failed', "
                        "updated_at = now() WHERE submission_id = :s"
                    ), {"s": sid})
                    await db.commit()
                    failed += 1
                    await _dm(uid, f"{ce('📍')} С твоим событием загвоздка: {reason}. Проверь данные и "
                                   "пришли ещё раз — Профиль → «Предложить событие».")
            elif kind == "channel":
                uname = (data.get("username_norm") or "").strip().lower()
                if not uname:
                    continue
                ok = (await db.execute(text(
                    "SELECT 1 FROM ref.sources s JOIN events.source_runs r "
                    "  ON r.source_id = s.source_id AND r.status = 'success' "
                    "WHERE s.name = :n LIMIT 1"
                ), {"n": f"telegram_public:{uname}"})).first()
                if ok:
                    await db.execute(text(
                        "UPDATE ref.pending_submissions SET status='ingested', updated_at = now() "
                        "WHERE submission_id = :s"
                    ), {"s": sid})
                    await db.commit()
                    ingested += 1
                    await _dm(uid, f"{ce('✨')} <b>Готово!</b> Канал @{uname} подключён — собираем афишу, "
                                   "события уже появляются на карте. Спасибо!")
    if ingested or failed:
        print(f"submissions-status-watch: ingested={ingested} failed={failed}")
    return {"ingested": ingested, "failed": failed}


@flow(name="pipeline-backlog-watch", retries=1, retry_delay_seconds=30, timeout_seconds=120, log_prints=True)
async def pipeline_backlog_watch():
    """Алерт владельцу, если встала ОБРАБОТКА (а не фетч). source_freshness_watch следит за коннекторами;
    этот — за ВОЗРАСТОМ головы и глубиной очередей normalize/enrich/dedup. Ловит ровно «3957 застряло на
    сутки, никто не заметил»: если самый старый необработанный raw старше STALE_H ч (очередь не движется)
    ИЛИ любая очередь глубже DEPTH_ALERT — DM (throttle раз в ~6ч). Возраст головы важнее числа — разовый
    всплеск ингеста сам рассосётся и голову не состарит. Считаем только НИКОГДА-не-пробованные raw
    (llm_attempts=0): иначе retry_transient_skips, переоткрывая старые llm_error-посты (они несут свой
    старый fetched_at), ложно триггерил бы «старейший N дней» — это ретрай-churn, а не застой."""
    from datetime import datetime, timezone

    import httpx
    from sqlalchemy import text

    from core.config.settings import get_settings
    from core.db.session import WorkerAsyncSessionLocal
    from core.infra.redis import get_redis

    STALE_H = 4       # голова очереди normalize старше 4ч = застой (а не медленный дренаж большого скана)
    DEPTH_ALERT = 8000
    settings = get_settings()
    owner = settings.admin_test_user_id or 5222335152
    async with WorkerAsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT "
            "(SELECT count(*) FROM events.raw_events re WHERE re.skip_reason = '' AND re.llm_attempts = 0 "
            "   AND NOT EXISTS (SELECT 1 FROM events.event_candidates c WHERE c.raw_id = re.raw_id)), "
            "(SELECT extract(epoch FROM now() - min(re.fetched_at)) / 3600 FROM events.raw_events re "
            "   WHERE re.skip_reason = '' AND re.llm_attempts = 0 AND NOT EXISTS (SELECT 1 FROM events.event_candidates c WHERE c.raw_id = re.raw_id)), "
            "(SELECT count(*) FROM events.event_candidates c WHERE c.venue_id IS NULL), "
            "(SELECT count(*) FROM events.event_candidates c WHERE c.venue_id IS NOT NULL "
            "   AND NOT EXISTS (SELECT 1 FROM events.event_sources es WHERE es.raw_id = c.raw_id))"
        ))).first()
    norm_n = int(row[0] or 0)
    oldest_h = float(row[1]) if row[1] is not None else 0.0
    enrich_n = int(row[2] or 0)
    dedup_n = int(row[3] or 0)
    result = {"norm": norm_n, "oldest_h": round(oldest_h, 1), "enrich": enrich_n, "dedup": dedup_n, "notified": False}
    # Возрастной триггер — только при СУЩЕСТВЕННОЙ глубине (≥AGE_MIN_DEPTH): несколько старых хвостов,
    # дренирующихся после восстановления, не должны слать алерт; реальный застой быстро копит сотни.
    # Депт-бэкстоп ловит огромный бэклог независимо от возраста.
    AGE_MIN_DEPTH = 250
    stalled = (norm_n >= AGE_MIN_DEPTH and oldest_h >= STALE_H) or max(norm_n, enrich_n, dedup_n) >= DEPTH_ALERT
    if not stalled or not settings.telegram_bot_token:
        return result
    now = datetime.now(timezone.utc)
    client = get_redis(decode=True)
    if client is not None:
        try:
            key = f"backlogwatch:{now:%Y%m%d}-{now.hour // 6}"  # один алерт на ~6-часовое окно
            if not await client.set(key, "1", nx=True, ex=7 * 3600):
                return result
        except Exception:
            pass
    msg = ("⚠️ <b>Пайплайн застрял</b> (обработка стоит, не фетч)\n\n"
           f"• normalize: <b>{norm_n}</b> необработанных, старейший <b>{round(oldest_h, 1)}ч</b>\n"
           f"• enrich: {enrich_n} без площадки\n"
           f"• dedup: {dedup_n} ждут дедуп\n\n"
           "Глянь prefect-serve (раннер/слоты/abort), LLM-эндпойнт, sweep-orphan-concurrency.")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                         json={"chat_id": int(owner), "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True})
        result["notified"] = True
    except Exception:
        pass
    return result


@flow(name="city-coverage-watch", retries=1, retry_delay_seconds=30, timeout_seconds=120, log_prints=True)
async def city_coverage_watch():
    """Телеметрия ПОКРЫТИЯ по городам + алерт на «пустую карту в городе X». По каждому активному городу:
    будущие события, % с гео (venue.geom — без него событие НЕ на карте) и % с фото. Полная таблица в лог
    (видно в Prefect). DM владельцу, если активный (крупный) город — слепое пятно: событий < MIN_EVENTS
    ИЛИ гео < MIN_GEO_PCT (события есть, а карта пустая = сломан источник/геокодинг). Throttle раз в день."""
    from datetime import datetime, timezone

    import httpx
    from sqlalchemy import text

    from core.config.settings import get_settings
    from core.db.session import WorkerAsyncSessionLocal
    from core.domain.cities import active_cities
    from core.infra.redis import get_redis

    MIN_EVENTS, MIN_GEO_PCT = 15, 55
    settings = get_settings()
    owner = settings.admin_test_user_id or 5222335152
    names = [c.name for c in active_cities()]
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT v.city, count(DISTINCT e.event_id) n, "
            "count(DISTINCT e.event_id) FILTER (WHERE v.geom IS NOT NULL) geo, "
            "count(DISTINCT e.event_id) FILTER (WHERE coalesce(e.cached_image_url, e.primary_image_url) IS NOT NULL) photo "
            "FROM events.events e JOIN events.event_occurrences o ON o.event_id = e.event_id "
            "JOIN events.venues v ON v.venue_id = o.venue_id "
            "WHERE e.status = 'active' AND coalesce(o.date_end, o.date_start) >= now() AND v.city = ANY(:c) GROUP BY v.city"
        ), {"c": names})).all()
    cov: dict = {}
    for city, n, geo, photo in rows:
        n = int(n or 0)
        cov[city] = {"n": n, "geo": round(100 * (geo or 0) / n) if n else 0, "photo": round(100 * (photo or 0) / n) if n else 0}
    for name in names:
        cov.setdefault(name, {"n": 0, "geo": 0, "photo": 0})  # город без событий = слепое пятно
    print("city_coverage:", cov)
    blind = [(c, m) for c, m in cov.items() if m["n"] < MIN_EVENTS or m["geo"] < MIN_GEO_PCT]
    result = {"coverage": cov, "blind": [b[0] for b in blind], "notified": False}
    if not blind or not settings.telegram_bot_token:
        return result
    now = datetime.now(timezone.utc)
    client = get_redis(decode=True)
    day = now.strftime("%Y%m%d")
    lines = []
    for city, m in blind:
        if client is not None:
            try:
                if not await client.set(f"covwatch:{city}:{day}", "1", nx=True, ex=2 * 24 * 3600):
                    continue
            except Exception:
                pass
        why = "мало событий" if m["n"] < MIN_EVENTS else f"низкое гео {m['geo']}%"
        lines.append(f"• <b>{city}</b> — {m['n']} событий, гео {m['geo']}%, фото {m['photo']}% ({why})")
    if not lines:
        return result
    msg = "⚠️ <b>Пустая карта в городе</b>\n\n" + "\n".join(lines) + "\n\nПроверь источники/геокодинг этих городов."
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                         json={"chat_id": int(owner), "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True})
        result["notified"] = True
    except Exception:
        pass
    return result


@flow(name="reprocess-changed", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=900, log_prints=True)
async def reprocess_changed():
    # Re-normalize structured-source raws whose content changed since first ingest (date shift / price
    # appears) so candidates + occurrences don't freeze forever.
    return await normalize._reprocess_changed_impl()


@flow(name="enrich-candidates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def enrich_candidates():
    return await enrich._enrich_impl()


@flow(name="dedup-candidates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def dedup_candidates():
    return await dedup._dedup_impl()


@flow(name="dedup-llm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
async def dedup_llm():
    """LLM-assisted dedup of same-venue+same-time pairs the rules can't resolve
    (declension/initials/wrapper-word variants). Cached + blocked, so cheap in
    steady state."""
    return await dedup._dedup_llm_impl(apply=True)


@flow(name="dedup-fuzzy-llm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=900, log_prints=True)
async def dedup_fuzzy_llm():
    """Daily: LLM-judge the REVIEW-tier fuzzy pairs (same venue+day, subset/high-ratio titles) and merge
    only high-confidence twins, so cross-source alt-naming dups self-heal instead of accumulating."""
    return await dedup._dedup_fuzzy_llm_impl(apply=True)


@flow(name="merge-duplicate-venues", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
def merge_duplicate_venues():
    return dedup._merge_venues_impl()


@flow(name="merge-duplicate-events", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=600, log_prints=True)
def merge_duplicate_events():
    return dedup._merge_events_impl()


@flow(name="expire-past-events", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def expire_past_events():
    """Lifecycle: first prune phantom future dates (a session a source no longer
    lists — the add-only upsert never deletes them), THEN expire events whose last
    live occurrence has passed and revive any that gained an upcoming one. Pruning
    before expiry means an event left with only a cancelled future date expires now
    instead of lingering until that phantom date passes."""
    from pipeline.maintenance.lifecycle import expire_past_events as _expire
    from pipeline.maintenance.prune_stale_occurrences import prune

    pruned = prune(apply=True)
    expired = _expire(apply=True)
    return {"pruned": pruned, "expired": expired}


@flow(name="resolve-afisha-dates", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
async def resolve_afisha_dates():
    """Fill exact dates for afisha-ONLY multi-show events (Yandex covers the rest in
    bulk). Small, polite, idempotent — only the few hundred events not on Yandex."""
    from pipeline.maintenance.resolve_afisha_dates import resolve

    return await resolve(apply=True)


@flow(name="self-heal-dedup", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def self_heal_dedup():
    """Runs frequently to close the small window where two sources put one event
    at two not-yet-merged venue rows. Order matters: collapse the duplicate
    venues first, then the events now sitting at the shared venue. Idempotent and
    near-instant when there is nothing to merge."""
    venues = dedup._merge_venues_impl()
    events = dedup._merge_events_impl()
    # Then split events that (now) span >1 physical place — the per-session venue
    # assignment in resolve_afisha_dates makes a touring show one event with several
    # venues, which must become one event per venue. Idempotent once split.
    from pipeline.maintenance.resplit import resplit

    split = resplit(apply=True)
    return {"venues": venues, "events": events, "resplit": split}


# --- enrichment side-jobs ----------------------------------------------------

@flow(name="backfill-venues-osm", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
async def backfill_venues_osm():
    return await enrich._backfill_venues_osm_impl()


@flow(name="correct-venue-coords", retries=1, retry_delay_seconds=120, timeout_seconds=1800, log_prints=True)
async def correct_venue_coords():
    """Fix venue coords that arrived verbatim from a source feed and landed off the real address (e.g. НЭТ
    Волгоград sat ~140 m past Аллея Героев). Re-geocodes the address house-precisely (Yandex) and moves the
    pin when the stored 'source' point disagrees materially. Self-healing: marks each venue reviewed so it
    pays once, and picks up newly-ingested 'source' venues on the next run. Idempotent."""
    from pipeline.maintenance.venue_coords import correct_venue_coordinates

    return await correct_venue_coordinates(apply=True, limit=800)


@flow(name="resolve-venue-hours", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def resolve_venue_hours():
    return enrich._resolve_venue_hours_impl()


@flow(name="cache-event-images", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
def cache_event_images():
    return media._cache_event_images_impl()


@flow(name="cache-telegram-images", retries=_RETRIES, retry_delay_seconds=_RETRY_DELAY, timeout_seconds=1200, log_prints=True)
async def cache_telegram_images():
    """Lazily download photos only for telegram EVENTS (posts that survived the pipeline), via Telethon."""
    return await media._cache_telegram_images_impl()


# --- re-engagement (outbound) ------------------------------------------------

@flow(name="send-reminders", retries=1, retry_delay_seconds=15, timeout_seconds=300, log_prints=True)
async def send_reminders():
    """DM users a bot reminder for saved events whose start is near (the first outbound
    channel). Idempotent: each reminder row is stamped sent_at after a delivered/permanent
    Telegram response, so a retry never double-sends."""
    return await reminders._send_reminders_impl()


@flow(name="welcome-nudge", retries=1, retry_delay_seconds=30, timeout_seconds=300, log_prints=True)
async def welcome_nudge():
    """D1-нудж: один персональный DM «события рядом» юзеру, открывшему апп ~сутки назад и ничего не
    сохранившему. Закрывает молчание до пятничного дайджеста. Идемпотентно (welcome_nudge_at)."""
    from apps.worker.tasks import welcome
    return await welcome._send_welcome_nudges_impl()


@flow(name="send-digest", retries=1, retry_delay_seconds=30, timeout_seconds=300, log_prints=True)
async def send_digest():
    """Weekly opt-in roundup DM: new at followed venues + the best of the coming weekend.
    Idempotent via a per-user last_digest_sent_at ledger (stamped on any Telegram response,
    checked against this ISO-week's start), so retries=1 is safe — a retry only re-sends to
    users a transient failure left unstamped, never a duplicate."""
    return await digest._send_digest_impl()


@flow(name="dispatch-broadcasts", retries=0, timeout_seconds=1800, log_prints=True)
async def dispatch_broadcasts():
    """Подхватить ДОЗРЕВШИЕ кастомные рассылки (now / at_utc) и отправить paced-сендером. retries=0 —
    механизм возобновления = поюзерный ledger (ON CONFLICT), а не повтор флоу (иначе риск дабл-сенда)."""
    return await broadcasts._dispatch_due_impl()


@flow(name="refresh-adstat-subs", retries=1, retry_delay_seconds=120, timeout_seconds=5400, log_prints=True)
def refresh_adstat_subs():
    """Обновить реальные подписчики adstat-каналов из t.me (точнее каталога Telega) + пересчитать НАШ скор
    (качество×релевантность) на актуальных подписчиках."""
    from apps.adstat.score import recompute_scores
    from apps.adstat.tme import refresh_subscribers
    r = refresh_subscribers(limit=600)
    s = recompute_scores()
    return {**r, **s}


@flow(name="classify-adstat-llm", retries=1, retry_delay_seconds=120, timeout_seconds=3600, log_prints=True)
def classify_adstat_llm():
    """LLM-классификация каналов (релевантность точнее кейвордов: «билеты ПДД»→мусор и т.п.) + пересчёт скора."""
    from apps.adstat.llm_classify import classify_channels_llm
    from apps.adstat.score import recompute_scores
    r = classify_channels_llm(limit=400)
    s = recompute_scores()
    return {**r, **s}


@flow(name="antifraud-scan-adstat", retries=0, timeout_seconds=5400, log_prints=True)
def antifraud_scan_adstat():
    """Анти-накрутка скан актуального пула (verdict≠мимо): разброс просмотров (t.me/s) + динамика роста
    (TGStat через FlareSolverr) + когерентность реакций → множитель `antifraud`, затем пересчёт скора.
    Ловит «надутые» каналы (плоский охват/спайк-заливка/мёртвая аудитория), которые точечный ERR не видит."""
    from apps.adstat.antifraud import antifraud_scan
    from apps.adstat.score import recompute_scores
    r = antifraud_scan(limit=200)
    s = recompute_scores()
    return {**r, **s}


@flow(name="enrich-adstat-telethon", retries=0, timeout_seconds=5400, log_prints=True)
def enrich_adstat_telethon():
    """Дообогатить точными метриками (telethon participants_count + охват) on-topic каналы без свежего
    реального охвата — для каналов с закрытым t.me-превью это единственный точный источник. retries=0
    (флуд-чувствительно). Малый батч + FloodWait-безопасный пул."""
    from apps.adstat.score import recompute_scores
    from apps.adstat.telethon_src import enrich_shortlist
    r = enrich_shortlist(limit=150)
    s = recompute_scores()
    return {**r, **s}

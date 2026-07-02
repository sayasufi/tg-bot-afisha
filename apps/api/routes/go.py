"""Партнёрский редирект тикет-кликов: GET /v1/go/{occurrence_id}.

Единая серверная точка между кнопкой «купить билет» в аппе и площадкой-продавцом. Делает три вещи:
 1) серверно логирует клик (авторитетнее фронтового intent — не теряется на закрытии вебвью / блокировке JS),
 2) для целей Afisha.ru оборачивает ссылку в Admitad-партнёрку с SubID = код события (для последующего
    S2S-постбэка и атрибуции продажи); для прочих целей (Яндекс.Афиша — трекается ТОЛЬКО по промокодам, не по
    ссылке; t.me / kudago) — прозрачный pass-through,
 3) 302-редиректит на итоговый URL.

Пока AFFILIATE_ADMITAD_AFISHA_GATEWAY пуст — это просто авторитетный клик-трекер + health мёртвых ссылок;
включение партнёрки = выставить env (после регистрации в Admitad), без изменения кода или фронта.
"""
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

_SAFE_REDIRECT_SCHEMES = {"http", "https"}  # запрещаем javascript:/data:/tg: и прочие open-redirect-схемы


def _is_safe_redirect(url: str) -> bool:
    """Разрешаем 302 только на http(s). source_best_url приходит из внешних источников —
    если там окажется javascript:/data:/иная схема, редирект на неё = open-redirect/XSS-вектор."""
    try:
        return (urlparse(url).scheme or "").lower() in _SAFE_REDIRECT_SCHEMES
    except Exception:
        return False
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import get_settings
from core.db.session import get_async_db
from core.domain.codes import event_code
from core.infra.redis import get_redis

router = APIRouter(prefix="/v1", tags=["go"])


def _is_afisha_ru(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "afisha.ru" or host.endswith(".afisha.ru")


def _wrap_affiliate(url: str, code: str | None) -> str:
    """Оборачивает Afisha.ru-URL в Admitad-gateway (ulp = целевой URL + SubID-метки), если gateway задан.
    Любую другую цель (или при пустом gateway) возвращает как есть — прозрачный pass-through."""
    s = get_settings()
    gw = s.affiliate_admitad_afisha_gateway.strip()
    if not gw or not _is_afisha_ru(url):
        return url
    params = [f"ulp={quote(url, safe='')}"]
    if code:
        params.append(f"subid={quote(code, safe='')}")  # subid = публичный код события → атрибуция в постбэке
    tag = s.affiliate_subid_tag.strip()
    if tag:
        params.append(f"subid1={quote(tag, safe='')}")  # subid1 = метка источника («okrest»)
    return gw.rstrip("/") + "/?" + "&".join(params)


@router.get("/go/{occurrence_id}")
async def go(occurrence_id: int, db: AsyncSession = Depends(get_async_db)):
    row = (await db.execute(text(
        "SELECT o.source_best_url AS url, e.display_no AS display_no, v.city AS city "
        "FROM events.event_occurrences o "
        "JOIN events.events e ON e.event_id = o.event_id "
        "LEFT JOIN events.venues v ON v.venue_id = o.venue_id "
        "WHERE o.occurrence_id = :oid"
    ), {"oid": occurrence_id})).mappings().first()

    settings = get_settings()
    fallback = settings.telegram_webapp_url or "https://app.okrestmap.ru"
    if not row or not (row["url"] or "").strip():
        return RedirectResponse(fallback, status_code=302)  # мёртвая/пустая ссылка → не тупик, назад в апп

    target = row["url"].strip()
    if not _is_safe_redirect(target):  # не http(s) (javascript:/data:/…) → не редиректим на вредоносную схему
        return RedirectResponse(fallback, status_code=302)
    code = event_code(row["display_no"], row["city"])

    rc = get_redis(decode=True)
    if rc is not None:
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            pipe = rc.pipeline()
            pipe.incr(f"go:clicks:{day}")                   # суточный счётчик тикет-кликов (воронка/доход)
            pipe.expire(f"go:clicks:{day}", 120 * 24 * 3600)
            pipe.hincrby("go:occ", str(occurrence_id), 1)   # клики по сеансу → сигнал для health мёртвых ссылок
            await pipe.execute()
        except Exception:  # клик-трекинг best-effort, НИКОГДА не ломает редирект
            pass

    return RedirectResponse(_wrap_affiliate(target, code), status_code=302)

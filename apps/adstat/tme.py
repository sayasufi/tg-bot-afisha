"""adstat: реальный счётчик подписчиков из публичного превью t.me.

Каталог Telega.in отдаёт устаревший `data-count` (напр. 52к против реальных 216к). Превью t.me/<username>
показывает живое число («216 221 subscribers») прямо в HTML — без авторизации. Пишем снапшот source='tme',
который админка предпочитает каталожным числам. У части каналов превью отключено → счётчика нет, их
оставляем на лучшем доступном источнике (telethon/telemetr/telega).
"""
import re
import time

from curl_cffi import requests as creq
from sqlalchemy import text

from core.db.session import SessionLocal

_H = {"Accept-Language": "en-US,en;q=0.9"}
_PACE = 0.4
_RE = re.compile(r"([\d][\d\s]{0,13})\s*(?:subscriber|member|подписчик)", re.I)


def fetch_subscribers(username: str) -> int | None:
    """Живое число подписчиков из t.me/<username>, или None если превью без счётчика/ошибка."""
    try:
        html = creq.get(f"https://t.me/{username}", impersonate="chrome", timeout=20, headers=_H).text
    except Exception:
        return None
    m = _RE.search(html)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def refresh_subscribers(limit: int = 400) -> dict:
    """Обновить реальные подписчики (source='tme') для каналов, не обновлённых с t.me за ~сутки.
    Крупнейшие сначала (по последнему известному числу) — у них чаще всего расхождение и они важнее."""
    db = SessionLocal()
    n_ok = n_none = 0
    try:
        rows = db.execute(text(
            "SELECT c.channel_id, c.username FROM adstat.channels c "
            "LEFT JOIN LATERAL (SELECT subscribers FROM adstat.snapshots s "
            "  WHERE s.channel_id = c.channel_id ORDER BY captured_at DESC LIMIT 1) last ON true "
            "WHERE c.username <> '' "
            "AND NOT EXISTS (SELECT 1 FROM adstat.snapshots t WHERE t.channel_id = c.channel_id "
            "                AND t.source = 'tme' AND t.captured_at > now() - interval '20 hours') "
            "ORDER BY COALESCE(last.subscribers, 0) DESC LIMIT :lim"
        ), {"lim": limit}).all()
        for cid, uname in rows:
            subs = fetch_subscribers(uname)
            if subs and subs > 0:
                db.execute(text(
                    "INSERT INTO adstat.snapshots (channel_id, source, captured_at, subscribers) "
                    "VALUES (:c, 'tme', now(), :s)"
                ), {"c": cid, "s": subs})
                db.commit()
                n_ok += 1
            else:
                n_none += 1
            time.sleep(_PACE)
    finally:
        db.close()
    return {"refreshed": n_ok, "no_count": n_none}

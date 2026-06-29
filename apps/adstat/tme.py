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
_RE_SUBS = re.compile(r"([\d][\d\s]{0,13})\s*(?:subscriber|member|подписчик)", re.I)
_RE_VIEWS = re.compile(r"message_views[^>]*>([^<]+)<")


def _num(s: str) -> int | None:
    """«1.2K» → 1200, «256» → 256."""
    s = s.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    mult = 1
    if s[-1:] in ("K", "k", "к"):
        mult, s = 1000, s[:-1]
    elif s[-1:] in ("M", "m", "м"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return None


def fetch_subscribers(username: str) -> int | None:
    """Живое число подписчиков из t.me/<username>, или None если превью без счётчика/ошибка."""
    try:
        html = creq.get(f"https://t.me/{username}", impersonate="chrome", timeout=20, headers=_H).text
    except Exception:
        return None
    m = _RE_SUBS.search(html)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def fetch_reach(username: str) -> int | None:
    """Реальный средний охват = среднее просмотров последних постов из t.me/s/<username>. Точнее
    каталожного avg_reach (тот часто завышен/устарел). None если постов/просмотров нет."""
    try:
        html = creq.get(f"https://t.me/s/{username}", impersonate="chrome", timeout=20, headers=_H).text
    except Exception:
        return None
    nums = [n for n in (_num(v) for v in _RE_VIEWS.findall(html)) if n]
    return sum(nums) // len(nums) if nums else None


def refresh_subscribers(limit: int = 400) -> dict:
    """Обновить реальные подписчики (source='tme') для каналов, не обновлённых с t.me за ~сутки.
    Крупнейшие сначала (по последнему известному числу) — у них чаще всего расхождение и они важнее."""
    db = SessionLocal()
    n_ok = n_none = 0
    try:
        # Порядок — по РЕЙТИНГУ (как в шортлисте админки): сначала каналы, которые реально смотрят.
        # Telega-число занижено у части каналов, поэтому сортировать по нему нельзя (важные уйдут в конец).
        rows = db.execute(text(
            "SELECT c.channel_id, c.username FROM adstat.channels c "
            "LEFT JOIN LATERAL (SELECT rating FROM adstat.snapshots s "
            "  WHERE s.channel_id = c.channel_id AND s.source <> 'tme' ORDER BY captured_at DESC LIMIT 1) m ON true "
            "WHERE c.username <> '' "
            "AND NOT EXISTS (SELECT 1 FROM adstat.snapshots t WHERE t.channel_id = c.channel_id "
            "                AND t.source = 'tme' AND t.captured_at > now() - interval '20 hours') "
            "ORDER BY COALESCE(m.rating, 0) DESC LIMIT :lim"
        ), {"lim": limit}).all()
        for cid, uname in rows:
            subs = fetch_subscribers(uname)
            time.sleep(_PACE)
            reach = fetch_reach(uname)
            subs = subs if (subs and subs > 0) else None
            reach = reach if (reach and reach > 0) else None
            if subs or reach:
                db.execute(text(
                    "INSERT INTO adstat.snapshots (channel_id, source, captured_at, subscribers, avg_reach) "
                    "VALUES (:c, 'tme', now(), :s, :r)"
                ), {"c": cid, "s": subs, "r": reach})
                db.commit()
                n_ok += 1
            else:
                n_none += 1
            time.sleep(_PACE)
    finally:
        db.close()
    return {"refreshed": n_ok, "no_count": n_none}

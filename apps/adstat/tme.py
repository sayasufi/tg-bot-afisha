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
# Реакция: <span class="tgme_reaction">…</i>97</span> — счётчик после эмодзи (</i>).
_RE_REACT = re.compile(r'class="tgme_reaction".*?</i>([\d.,KkМмKk\s]+)</span>', re.DOTALL)


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


def fetch_post_stats(username: str) -> tuple[int | None, int | None]:
    """Из t.me/s/<username>: (средний охват = среднее просмотров последних постов, средние реакции на
    пост). Точнее каталога. (None, None) если превью без постов/ошибка."""
    try:
        html = creq.get(f"https://t.me/s/{username}", impersonate="chrome", timeout=20, headers=_H).text
    except Exception:
        return None, None
    views = [n for n in (_num(v) for v in _RE_VIEWS.findall(html)) if n]
    avg_reach = sum(views) // len(views) if views else None
    rcounts = [n for n in (_num(v) for v in _RE_REACT.findall(html)) if n]
    posts_with_react = html.count("js-message_reactions")  # постов с реакциями
    avg_reactions = sum(rcounts) // posts_with_react if (rcounts and posts_with_react) else None
    return avg_reach, avg_reactions


def refresh_subscribers(limit: int = 600) -> dict:
    """Обновить реальные подписчики (source='tme') для каналов, не обновлённых с t.me за ~сутки.
    Приоритет: on-topic → НИКОГДА-не-проверенные t.me (только telega, число часто врёт) → по рейтингу."""
    db = SessionLocal()
    n_ok = n_none = 0
    try:
        # Порядок отбора (важно!): каналы с ТОЛЬКО telega-числом часто занижены (telega врёт), а сортировка по
        # их же rating уводила их в хвост → t.me-проверка до них не доходила → врали вечно (@voronczova1970:
        # telega 2306 vs t.me 29373). Поэтому НИКОГДА-не-проверенные t.me ставим вперёд, on-topic — раньше всех.
        rows = db.execute(text(
            "SELECT c.channel_id, c.username FROM adstat.channels c "
            "LEFT JOIN LATERAL (SELECT rating FROM adstat.snapshots s "
            "  WHERE s.channel_id = c.channel_id AND s.source <> 'tme' ORDER BY captured_at DESC LIMIT 1) m ON true "
            "WHERE c.username <> '' "
            # перепрогоняем, пока у свежего tme-снапшота нет ОХВАТА (ранние писали только подписчиков)
            "AND NOT EXISTS (SELECT 1 FROM adstat.snapshots t WHERE t.channel_id = c.channel_id "
            "                AND t.source = 'tme' AND t.avg_reach IS NOT NULL AND t.captured_at > now() - interval '20 hours') "
            "ORDER BY (c.relevance = ANY(ARRAY['афиша','город/локалка'])) DESC, "
            "  (NOT EXISTS (SELECT 1 FROM adstat.snapshots t2 WHERE t2.channel_id = c.channel_id "
            "               AND t2.source = 'tme' AND t2.subscribers IS NOT NULL)) DESC, "
            "  COALESCE(m.rating, 0) DESC LIMIT :lim"
        ), {"lim": limit}).all()
        for cid, uname in rows:
            subs = fetch_subscribers(uname)
            time.sleep(_PACE)
            reach, reactions = fetch_post_stats(uname)
            subs = subs if (subs and subs > 0) else None
            reach = reach if (reach and reach > 0) else None
            reactions = reactions if (reactions and reactions > 0) else None
            if subs or reach:
                db.execute(text(
                    "INSERT INTO adstat.snapshots (channel_id, source, captured_at, subscribers, avg_reach, avg_reactions) "
                    "VALUES (:c, 'tme', now(), :s, :r, :rx)"
                ), {"c": cid, "s": subs, "r": reach, "rx": reactions})
                db.commit()
                n_ok += 1
            else:
                n_none += 1
            time.sleep(_PACE)
    finally:
        db.close()
    return {"refreshed": n_ok, "no_count": n_none}

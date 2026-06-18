"""Shared presentation helpers for bot messages."""
from datetime import datetime, timedelta, timezone
from html import escape

_MSK = timezone(timedelta(hours=3))

# Short category codes — MUST mirror miniapp sheetFormat.ts CAT_CODE so the accession
# line in a bot DM ("MSK-04PN · ТЕАТР") matches the one in the event sheet exactly.
CAT_CODE = {
    "concert": "КОНЦ", "theatre": "ТЕАТР", "exhibition": "ВЫСТ", "cinema": "КИНО",
    "standup": "СТЕНД", "festival": "ФЕСТ", "lecture": "ЛЕКЦ", "tour": "ЭКСК",
    "party": "ВЕЧЕР", "kids": "ДЕТИ", "other": "ПРОЧ",
}

_WEEKDAY_PREP = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]

CATEGORY_GLYPH = {
    "concert": "🎵",
    "theatre": "🎭",
    "exhibition": "🖼",
    "cinema": "🎬",
    "standup": "🎤",
    "festival": "🎪",
    "lecture": "🎓",
    "tour": "🗺",
    "party": "🥂",
    "quest": "🗝",
    "kids": "🧸",
    "other": "✨",
}

_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def glyph(category: str | None) -> str:
    return CATEGORY_GLYPH.get(category or "", "✨")


def format_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]}, {dt:%H:%M}"


def format_price(price) -> str:
    if price is None:
        return "Цена не указана"
    try:
        value = float(price)
    except (TypeError, ValueError):
        return "Цена не указана"
    if value == 0:
        return "Бесплатно"
    return f"от {int(value)} ₽"


def event_card(item: dict) -> str:
    title = escape(str(item.get("title") or "Без названия"))
    lines = [f"{glyph(item.get('category'))} <b>{title}</b>"]
    date = format_date(item.get("date_start"))
    if date:
        lines.append(f"📅 {date}")
    venue = item.get("venue")
    if venue:
        lines.append(f"📍 {escape(str(venue))}")
    lines.append(f"💰 {format_price(item.get('price_min'))}")
    return "\n".join(lines)


def _plural(n: int, one: str, few: str, many: str) -> str:
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not (12 <= m100 <= 14):
        return few
    return many


def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    dt = v if isinstance(v, datetime) else None
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def when_phrase(start, end=None, now: datetime | None = None) -> str:
    """Urgency-first phrasing of WHEN, in Moscow time — answers 'should I act now?' at a
    glance: 'через 2 часа · сегодня в 09:30', 'завтра в 19:30', 'идёт сейчас · до 22:00'."""
    s = _parse_dt(start)
    if s is None:
        return ""
    now = now or datetime.now(timezone.utc)
    sm, nm = s.astimezone(_MSK), now.astimezone(_MSK)
    hhmm = f"{sm:%H:%M}"
    if s <= now:  # already started / ongoing
        e = _parse_dt(end)
        if e and e > now and e.astimezone(_MSK).date() == nm.date():
            return f"идёт сейчас · до {e.astimezone(_MSK):%H:%M}"
        return "идёт сейчас"
    secs = (s - now).total_seconds()
    days = (sm.date() - nm.date()).days
    if secs < 3600:
        mins = max(5, round(secs / 60 / 5) * 5)
        return f"через {mins} {_plural(mins, 'минуту', 'минуты', 'минут')} · в {hhmm}"
    if days == 0:
        hrs = round(secs / 3600)
        return f"через {hrs} {_plural(hrs, 'час', 'часа', 'часов')} · сегодня в {hhmm}"
    if days == 1:
        return f"завтра в {hhmm}"
    if 2 <= days <= 6:
        return f"{_WEEKDAY_PREP[sm.weekday()]}, {hhmm}"
    date_str = f"{sm.day} {_MONTHS[sm.month - 1]}"
    if sm.year != nm.year:
        date_str += f" {sm.year}"
    return f"{date_str}, {hhmm}"


def reminder_caption(item: dict, now: datetime | None = None) -> str:
    """A VITRINE-styled reminder caption (paired with the event's cover photo): an urgency
    hero line, the bold title, the accession code · category signature, and a wall-label
    blockquote of venue + price. On-brand, no emoji-soup, one meaningful bell."""
    raw = str(item.get("title") or "Событие")
    if len(raw) > 120:
        raw = raw[:119].rstrip() + "…"
    title = escape(raw)
    sig = " · ".join(p for p in [item.get("code"), CAT_CODE.get(item.get("category") or "", "ПРОЧ")] if p)
    when = when_phrase(item.get("date_start"), item.get("date_end"), now)

    lines = []
    if when:
        lines.append(f"🔔 <b>{when}</b>\n")
    lines.append(f"<b>{title}</b>")
    lines.append(f"<code>{sig}</code>")

    venue = escape(str(item.get("venue") or "").strip())
    price = item.get("price_min")
    price_str = "бесплатно" if price is not None and float(price) == 0 else (f"от {int(float(price))} ₽" if price is not None else "")
    wall = [v for v in [venue, f"<code>{price_str}</code>" if price_str else ""] if v]
    if wall:
        lines.append("\n<blockquote>" + "\n".join(wall) + "</blockquote>")
    return "\n".join(lines)

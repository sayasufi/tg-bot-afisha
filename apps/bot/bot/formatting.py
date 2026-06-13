"""Shared presentation helpers for bot messages."""
from datetime import datetime
from html import escape

CATEGORY_GLYPH = {
    "concert": "🎵",
    "theatre": "🎭",
    "exhibition": "🖼",
    "standup": "🎤",
    "festival": "🎪",
    "lecture": "🎓",
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

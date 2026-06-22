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

# Our VITRINE custom-emoji ids (set "vitrine_by_okrestmap_bot"). ce() wraps a standard
# emoji so it renders as our acid glyph in bot DMs, with that same emoji as the automatic
# fallback (shown in push-notification previews, or if the owner's Premium ever lapses).
CUSTOM_EMOJI = {
    "🔔": "5305380299666925175",
    "📍": "5305268063581542808",
    "⚡": "5305445248162371955",
    "➡️": "5303493739577122144",
    "🔴": "5305776145327755759",
}


def ce(emoji: str) -> str:
    cid = CUSTOM_EMOJI.get(emoji)
    return f'<tg-emoji emoji-id="{cid}">{emoji}</tg-emoji>' if cid else emoji

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
        lines.append(f"{ce('🔔')} <b>{when}</b>\n")
    lines.append(f"<b>{title}</b>")
    lines.append(f"<code>{sig}</code>")

    venue = escape(str(item.get("venue") or "").strip())
    price = item.get("price_min")
    price_str = "бесплатно" if price is not None and float(price) == 0 else (f"от {int(float(price))} ₽" if price is not None else "")
    wall = [v for v in [f"{ce('📍')} {venue}" if venue else "", f"<code>{price_str}</code>" if price_str else ""] if v]
    if wall:
        lines.append("\n<blockquote>" + "\n".join(wall) + "</blockquote>")
    return "\n".join(lines)


def reminder_caption_card(item: dict, now: datetime | None = None) -> str:
    """The caption under the fully-composed reminder card — the card itself shows when / title / code
    / venue / price, so this stays light: a bell + the urgency line (the RELATIVE part bold, the clock
    time dim) and the title as the bold hero, with breathing room between. Enough for the chat-list
    preview to read the event (vs a bare «Фото») without duplicating the whole wall."""
    raw = str(item.get("title") or "Событие")
    if len(raw) > 100:
        raw = raw[:99].rstrip() + "…"
    title = f"<b>{escape(raw)}</b>"
    when = when_phrase(item.get("date_start"), item.get("date_end"), now)
    if not when:
        return title
    # «через 2 часа · сегодня в 21:00» → bold the lead, keep the clock time quiet.
    lead, _, tail = when.partition(" · ")
    when_html = f"<b>{escape(lead)}</b>" + (f" · {escape(tail)}" if tail else "")
    return f"{ce('🔔')} {when_html}\n\n{title}"


_BOT_USERNAME = "okrestmap_bot"


def event_deeplink(event_id: str) -> str:
    """startapp link → opens the Mini App on this event (tappable title in a DM)."""
    return f"https://t.me/{_BOT_USERNAME}?startapp={event_id}"


def _price_short(price_min, price_max=None) -> str:
    """Mirror of the card's _price_str for captions: «бесплатно» only when truly free (0/0), «до N ₽»
    for a paid range that starts at 0, «от N ₽» with a real floor, empty when there's no price."""
    lo = float(price_min) if price_min is not None else None
    hi = float(price_max) if price_max is not None else None
    if lo and lo > 0:
        return f"от {int(lo)} ₽"
    if hi and hi > 0:
        return f"до {int(hi)} ₽"
    if lo == 0 or hi == 0:
        return "бесплатно"
    return ""


def weekend_label(sat, sun) -> str:
    """'20–21 июня', or '31 мая – 1 июня' when the weekend straddles two months."""
    if sat.month == sun.month:
        return f"{sat.day}–{sun.day} {_MONTHS[sat.month - 1]}"
    return f"{sat.day} {_MONTHS[sat.month - 1]} – {sun.day} {_MONTHS[sun.month - 1]}"


def _digest_line(item: dict, now: datetime | None) -> str:
    title = escape(str(item.get("title") or "Событие")[:90])
    # Accession code · when · venue — same signature grammar as reminder_caption, so a digest
    # row and a reminder for the same event read identically (the code is escaped + monospaced).
    sub = " · ".join(
        p
        for p in [
            escape(str(item.get("code") or "").strip()),
            when_phrase(item.get("date_start"), item.get("date_end"), now),
            escape(str(item.get("venue") or "").strip()),
        ]
        if p
    )
    line = f'{glyph(item.get("category"))} <a href="{event_deeplink(item["event_id"])}"><b>{title}</b></a>'
    return f"{line}\n<code>{sub}</code>" if sub else line


def digest_message(
    venue_items: list[dict],
    friend_items: list[dict],
    weekend_items: list[dict],
    label: str,
    now: datetime | None = None,
) -> str:
    """The weekly roundup DM: a hero, then 'new at your venues' (the follow loop), 'what friends saved',
    + the best of this weekend. Each title is a deep-link that opens the event in the Mini App."""
    now = now or datetime.now(timezone.utc)
    lines = [f"{ce('⚡')} <b>афиша на выходные</b>"]
    if label:
        lines.append(f"<i>{escape(label)}</i>")
    if venue_items:
        lines.append("\n<b>новое на ваших площадках</b>")
        lines.extend(_digest_line(it, now) for it in venue_items)
    if friend_items:
        lines.append(f"\n{ce('👥')} <b>что сохранили друзья</b>")
        lines.extend(_digest_line(it, now) for it in friend_items)
    if weekend_items:
        lines.append(f"\n{ce('📍')} <b>на выходных рядом</b>")
        lines.extend(_digest_line(it, now) for it in weekend_items)
    return "\n".join(lines)


def digest_caption(venue_items: list[dict], friend_items: list[dict], weekend_items: list[dict], label: str) -> str:
    """Caption UNDER the digest poster — the tappable index: a hero line, then sectioned events where
    each title is a BOLD deep-link into the Mini App with its price beside it. The poster carries the
    photos + venue; the caption carries the links + price, so it stays a clean, scannable agenda."""
    hero = f"{ce('⚡')} <b>афиша на выходные</b>"
    lines = [f"{hero} · <i>{escape(label)}</i>" if label else hero]

    def block(emoji: str, head: str, items: list[dict]) -> None:
        if not items:
            return
        lines.append(f"\n{ce(emoji)} <b>{head}</b>")
        for it in items:
            title = escape(str(it.get("title") or "Событие")[:80])
            link = f'<a href="{event_deeplink(it["event_id"])}"><b>{title}</b></a>'
            price = _price_short(it.get("price_min"), it.get("price_max"))
            lines.append(f"{glyph(it.get('category'))} {link}" + (f" · {price}" if price else ""))

    block("📍", "новое на твоих площадках", venue_items)
    block("👥", "что сохранили друзья", friend_items)
    block("✨", "на выходных рядом", weekend_items)
    return "\n".join(lines)

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

MAP_BUTTON_TEXT = "🗺 Открыть карту"


def _is_https(url: str) -> bool:
    # Telegram only renders web_app buttons over HTTPS; on local http we degrade.
    return url.startswith("https://")


def webapp_inline(webapp_url: str) -> InlineKeyboardButton:
    if _is_https(webapp_url):
        return InlineKeyboardButton(text=MAP_BUTTON_TEXT, web_app=WebAppInfo(url=webapp_url))
    return InlineKeyboardButton(text=MAP_BUTTON_TEXT, url=webapp_url)


def webapp_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    """A single inline button that opens the map."""
    return InlineKeyboardMarkup(inline_keyboard=[[webapp_inline(webapp_url)]])


def map_reply_keyboard(webapp_url: str) -> ReplyKeyboardMarkup | None:
    """Persistent bottom keyboard so the map is always one tap away.

    web_app reply buttons need HTTPS; on non-HTTPS dev we return None and the
    caller falls back to the inline button.
    """
    if not _is_https(webapp_url):
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MAP_BUTTON_TEXT, web_app=WebAppInfo(url=webapp_url))]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Открой карту — события уже рядом",
    )

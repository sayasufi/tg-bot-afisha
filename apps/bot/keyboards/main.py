from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

MAP_BUTTON_TEXT = "🗺 Открыть карту"


def location_request_keyboard() -> ReplyKeyboardMarkup:
    """Одна кнопка «поделиться геопозицией» для нового юзера без города — определяем ближайший город по гео
    (масштабируется на любое число городов, в отличие от сетки кнопок-городов). Скрывается после нажатия."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Определить мой город", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


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

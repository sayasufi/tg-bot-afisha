from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from core.domain.cities import active_cities

MAP_BUTTON_TEXT = "🗺 Открыть карту"


def city_picker_keyboard() -> InlineKeyboardMarkup:
    """Сетка кнопок выбора города (2 в ряд) для нового бот-юзера без города — callback `city:<slug>`."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for c in active_cities():
        row.append(InlineKeyboardButton(text=c.name, callback_data=f"city:{c.slug}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


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

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

CITIES = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург"]


def webapp_button(webapp_url: str) -> InlineKeyboardButton:
    # Telegram only accepts web_app buttons over HTTPS; otherwise degrade to a
    # plain URL button that opens the map in the browser.
    if webapp_url.startswith("https://"):
        return InlineKeyboardButton(text="🗺 Открыть карту", web_app=WebAppInfo(url=webapp_url))
    return InlineKeyboardButton(text="🗺 Открыть карту", url=webapp_url)


def _city_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text=a, callback_data=f"city:{a}"), InlineKeyboardButton(text=b, callback_data=f"city:{b}")]
        for a, b in (CITIES[0:2], CITIES[2:4])
    ]


def main_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[webapp_button(webapp_url)], *_city_rows()])


def city_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_city_rows())


def webapp_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[webapp_button(webapp_url)]])

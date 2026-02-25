from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo


def city_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Moscow"), KeyboardButton(text="Saint Petersburg")],
            [KeyboardButton(text="Kazan"), KeyboardButton(text="Yekaterinburg")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def webapp_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Open Map", web_app=WebAppInfo(url=webapp_url))]]
    )

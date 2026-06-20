from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

remove_keyboard = ReplyKeyboardRemove()


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📨 Elon berish"),
                KeyboardButton(text="📋 Mening elonlarim"),
            ],
            [
                KeyboardButton(text="💎 Obunalarim"),
                KeyboardButton(text="➕ Akkaunt qo'shish"),
            ],
            [
                KeyboardButton(text="📞 Admin bilan bog'lanish"),
            ],
        ],
        resize_keyboard=True,
    )


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📨 Elon berish"),
                KeyboardButton(text="📋 Mening elonlarim"),
            ],
            [
                KeyboardButton(text="💎 Obunalarim"),
                KeyboardButton(text="➕ Akkaunt qo'shish"),
            ],
            [
                KeyboardButton(text="🔐 Admin Panel"),
            ],
        ],
        resize_keyboard=True,
    )


def phone_share() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_only() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def skip_or_cancel() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ O'tkazib yuborish")],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True,
    )

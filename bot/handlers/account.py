"""
Handles adding a Telegram user-account via Telethon OTP flow.

Flow:
  1. User taps "➕ Akkaunt qo'shish"
  2. Bot asks for phone number (+998...)
  3. Telethon sends OTP via Telegram
  4. User types code in obfuscated format (e.g. "5.5 9-28") → digits extracted
  5. (Optional) 2FA password if enabled
  6. Session string saved; groups fetched and stored
"""

import re
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from database.models import Group, TelegramAccount, User
from userbot import manager
from bot.keyboards.reply import cancel_only, main_menu

router = Router()

CANCEL = "❌ Bekor qilish"


class AccountFSM(StatesGroup):
    phone = State()
    code = State()
    password = State()


def _user_is_active(user: User) -> bool:
    if user.is_premium:
        return True
    return bool(user.trial_expires_at and user.trial_expires_at > datetime.utcnow())


# ---------------------------------------------------------------------------

@router.message(F.text == "➕ Akkaunt qo'shish")
async def add_account(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("⚠️ Avval /start orqali ro'yxatdan o'ting!")
        return
    if not _user_is_active(user):
        from config import ADMIN_USERNAME
        await message.answer(f"❌ Sinov muddatingiz tugagan. Obuna uchun {ADMIN_USERNAME} bilan bog'laning.")
        return

    await state.set_state(AccountFSM.phone)
    await message.answer(
        "📱 <b>Telegram akkauntingizni ulash</b>\n\n"
        "Telefon raqamingizni xalqaro formatda yuboring:\n\n"
        "Misol: <code>+998901234567</code>\n\n"
        "⚠️ Tasdiqlash kodini qabul qilish uchun raqamingizga kirishingiz kerak.",
        reply_markup=cancel_only(),
        parse_mode="HTML",
    )


@router.message(AccountFSM.phone)
async def process_phone(message: Message, state: FSMContext) -> None:
    if message.text == CANCEL:
        await _cancel(message, state)
        return

    raw = message.text.strip().replace(" ", "")
    if not re.match(r"^\+?[0-9]{9,15}$", raw):
        await message.answer("⚠️ Noto'g'ri format. Misol: +998901234567")
        return

    phone = "+" + raw.lstrip("+")
    await message.answer("⏳ Kod yuborilmoqda...")

    try:
        await manager.start_login(message.from_user.id, phone)
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}\n\nQaytadan urinib ko'ring.")
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=main_menu())
        return

    await state.update_data(phone=phone)
    await state.set_state(AccountFSM.code)
    await message.answer(
        "📲 <b>Kod yuborildi!</b>\n\n"
        "Telegram akkauntingizga tasdiqlash kodi yuborildi.\n\n"
        "⚠️ MUHIM: Kodni <b>STANDART BO'LMAGAN</b> formatda yuboring:\n\n"
        "Misollar:\n"
        "• <code>1.2345</code>  (nuqta bilan)\n"
        "• <code>1 2 3 4 5</code>  (bo'sh joy bilan)\n"
        "• <code>1-2-3-4-5</code>  (chiziqcha bilan)",
        reply_markup=cancel_only(),
        parse_mode="HTML",
    )


@router.message(AccountFSM.code)
async def process_code(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text == CANCEL:
        await manager.cancel_login(message.from_user.id)
        await _cancel(message, state)
        return

    if not manager.has_login_session(message.from_user.id):
        await message.answer("⚠️ Sessiya topilmadi. Qaytadan boshlang.")
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=main_menu())
        return

    code = re.sub(r"\D", "", message.text.strip())
    if len(code) < 5:
        await message.answer("⚠️ Kod 5 ta raqamdan iborat bo'lishi kerak. Qaytadan kiriting.\n\nMisol: <code>1.2345</code>", parse_mode="HTML")
        return

    try:
        session_string, phone = await manager.finish_login(message.from_user.id, code)
    except SessionPasswordNeededError:
        await state.set_state(AccountFSM.password)
        await message.answer(
            "🔐 Akkauntingizda <b>2FA</b> yoqilgan.\n\nIltimos, parolingizni kiriting:",
            reply_markup=cancel_only(),
            parse_mode="HTML",
        )
        return
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await message.answer("❌ Noto'g'ri yoki muddati o'tgan kod. Qaytadan urinib ko'ring.")
        return
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=main_menu())
        return

    await _save_account_and_groups(message, state, session, session_string, phone)


@router.message(AccountFSM.password)
async def process_2fa(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text == CANCEL:
        await manager.cancel_login(message.from_user.id)
        await _cancel(message, state)
        return

    if not manager.has_login_session(message.from_user.id):
        await message.answer("⚠️ Sessiya topilmadi. Qaytadan boshlang.")
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=main_menu())
        return

    try:
        session_string, phone = await manager.finish_login_2fa(message.from_user.id, message.text.strip())
    except Exception as e:
        await message.answer(f"❌ Noto'g'ri parol: {e}")
        return

    await _save_account_and_groups(message, state, session, session_string, phone)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _save_account_and_groups(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    session_string: str,
    phone: str,
) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))

    # Upsert account
    account = await session.scalar(
        select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.phone == phone,
        )
    )
    if account:
        account.session_string = session_string
        account.is_active = True
    else:
        account = TelegramAccount(user_id=user.id, phone=phone, session_string=session_string)
        session.add(account)

    await session.flush()

    loading_msg = await message.answer("⏳ Guruhlar yuklanmoqda... (30-60 soniya kutish mumkin)")

    try:
        client = await manager.get_client(account.id, session_string)
        groups = await manager.fetch_groups(client)
    except Exception as e:
        await session.rollback()
        await message.answer(f"❌ Guruhlarni yuklashda xatolik: {e}")
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=main_menu())
        return

    # Upsert groups
    for g in groups:
        existing = await session.scalar(
            select(Group).where(Group.account_id == account.id, Group.chat_id == g["chat_id"])
        )
        if existing:
            existing.title = g["title"]
            existing.username = g["username"]
            existing.member_count = g["member_count"]
            existing.updated_at = datetime.utcnow()
        else:
            session.add(
                Group(
                    account_id=account.id,
                    chat_id=g["chat_id"],
                    title=g["title"],
                    username=g["username"],
                    member_count=g["member_count"],
                )
            )

    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>Akkaunt muvaffaqiyatli ulandi!</b>\n\n"
        f"📱 Telefon: {phone}\n"
        f"👥 Guruhlar soni: {len(groups)} ta\n\n"
        "Endi '📨 Elon berish' tugmasini bosing!",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


async def _cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu())

from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import TRIAL_HOURS
from database.models import User
from bot.keyboards.reply import main_menu, phone_share

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()  # Always clear any stuck FSM state on /start

    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))

    if user:
        await message.answer(
            f"👋 Xush kelibsiz, <b>{message.from_user.first_name}</b>!\n\n"
            "Quyidagi tugmalardan birini tanlang:",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Telegram guruhlarga qo'lda yozib o'tirmang — "
        "e'lonlaringizni bot o'zi avtomatik yuboradi! 🚀\n\n"
        "✨ <b>Bot imkoniyatlari:</b>\n"
        "• Guruhlarga avtomatik xabar yuborish\n"
        "• Matnli va rasmli xabarlarni yuborish\n"
        "• Yuborish oraliqlarini boshqarish\n"
        "• Xabarlar holatini kuzatish\n\n"
        "🔒 Boshlash uchun quyidagi tugma orqali telefon raqamingizni yuboring.\n\n"
        f"🎁 <b>{TRIAL_HOURS} soat bepul sinov muddati mavjud!</b>",
        reply_markup=phone_share(),
        parse_mode="HTML",
    )


@router.message(F.contact)
async def handle_contact(message: Message, session: AsyncSession) -> None:
    contact = message.contact

    if contact.user_id != message.from_user.id:
        await message.answer("⚠️ Iltimos, o'z raqamingizni yuboring!")
        return

    existing = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if existing:
        await message.answer("✅ Siz allaqachon ro'yxatdan o'tgansiz!", reply_markup=main_menu())
        return

    phone = contact.phone_number.replace("+", "").replace(" ", "")
    trial_end = datetime.utcnow() + timedelta(hours=TRIAL_HOURS)

    user = User(
        telegram_id=message.from_user.id,
        phone=phone,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
        trial_expires_at=trial_end,
    )
    session.add(user)
    await session.commit()

    await message.answer(
        "🎉 <b>Tabriklaymiz! Siz ro'yxatdan o'tdingiz!</b>\n\n"
        f"📱 Telefon: +{phone}\n"
        f"🎁 Sinov muddati: {TRIAL_HOURS} soat\n\n"
        "Siz botning barcha funksiyalaridan foydalanishingiz mumkin!\n\n"
        "Boshlash uchun '➕ Akkaunt qo'shish' tugmasini bosing.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )

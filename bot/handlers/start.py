from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import TRIAL_HOURS, ADMIN_IDS, ADMIN_USERNAME
from database.models import User
from bot.keyboards.reply import main_menu, admin_menu, phone_share

router = Router()


def _is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


def _get_menu(tg_id: int):
    return admin_menu() if _is_admin(tg_id) else main_menu()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()

    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))

    if user:
        extra = "\n\n🔐 <b>Siz admin sifatida kirgansiz.</b> '🔐 Admin Panel' tugmasini bosing." if _is_admin(message.from_user.id) else ""
        await message.answer(
            f"👋 Xush kelibsiz, <b>{message.from_user.first_name}</b>!{extra}\n\n"
            "Quyidagi tugmalardan birini tanlang:",
            reply_markup=_get_menu(message.from_user.id),
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

    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer("⚠️ Iltimos, o'z raqamingizni yuboring!")
        return

    existing = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if existing:
        await message.answer("✅ Siz allaqachon ro'yxatdan o'tgansiz!", reply_markup=_get_menu(message.from_user.id))
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
        "Boshlash uchun '➕ Akkaunt qo'shish' tugmasini bosing.",
        reply_markup=_get_menu(message.from_user.id),
        parse_mode="HTML",
    )


@router.message(F.text == "🔐 Admin Panel")
async def admin_panel_btn(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    from aiogram.filters import Command
    from bot.handlers.admin_panel import admin_cmd
    await admin_cmd(message)


@router.message(F.text == "📞 Admin bilan bog'lanish")
async def contact_admin(message: Message) -> None:
    await message.answer(
        f"📞 <b>Admin bilan bog'lanish</b>\n\n"
        f"Savol yoki muammo bo'lsa, admin bilan to'g'ridan to'g'ri bog'laning:\n\n"
        f"👤 {ADMIN_USERNAME}\n\n"
        f"Obuna va to'lov masalalarida ham shu manzilga murojaat qiling.",
        parse_mode="HTML",
    )

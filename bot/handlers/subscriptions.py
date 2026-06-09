"""
"Obunalarim" — subscription status + payment flow.

Screens:
  1. Status card: tarif, boshlandi, tugadi, aktiv xabarlar soni
     Buttons: Obunani uzaytirish | Tarifni o'zgartirish | Orqaga

  2. "Tarifni o'zgartirish" → shows tariff list
     Buttons: [1 oy — 50 000 so'm] [3 oy — 120 000 so'm] ... | Orqaga

  3. "Obunani uzaytirish" / tariff selected → shows payment card info
     "Iltimos, to'lov kvitansiyasini yuboring"
     Button: Bekor qilish

  4. User sends receipt photo → forwarded to admin(s)
     Bot: "Kvitansiya yuborildi! Administrator tekshiruidan so'ng obunangiz faollashtiriladi."
"""

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_IDS, ADMIN_USERNAME, CARD_OWNER, PAYMENT_CARD, TARIFFS
from database.models import Announcement, AnnouncementStatus, TelegramAccount, User
from bot.keyboards.inline import cancel_payment_kb, subscription_kb, tariff_kb
from bot.keyboards.reply import main_menu

router = Router()


class SubFSM(StatesGroup):
    waiting_receipt = State()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _trial_status(user: User) -> str:
    now = datetime.utcnow()
    if user.is_premium:
        return "💎 Premium"
    if user.trial_expires_at and user.trial_expires_at > now:
        return "🎁 Bepul sinov"
    return "❌ Muddati tugagan"


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


# ──────────────────────────────────────────────────────────────
# Main screen
# ──────────────────────────────────────────────────────────────

@router.message(F.text == "💎 Obunalarim")
async def subscriptions(message: Message, session: AsyncSession) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("⚠️ Avval /start orqali ro'yxatdan o'ting!")
        return

    active_count = len(list(await session.scalars(
        select(Announcement).where(
            Announcement.user_id == user.id,
            Announcement.status == AnnouncementStatus.scheduled,
            Announcement.is_active == True,
        )
    )))

    accounts = list(await session.scalars(
        select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True,
        )
    ))

    now = datetime.utcnow()
    expired = not user.is_premium and (
        not user.trial_expires_at or user.trial_expires_at <= now
    )

    text = (
        "💎 <b>Obunalarim</b>\n\n"
        f"📊 Aktiv xabarlar: {active_count} ta\n"
        f"📱 Akkauntlar: {len(accounts)} ta\n"
        f"💳 Tarif: {_trial_status(user)}\n"
        f"📅 Boshlandi: {_fmt_date(user.created_at)}\n"
        f"📅 Tugadi: {_fmt_date(user.trial_expires_at)}\n"
    )
    if expired:
        text += f"\n⚠️ Obunangizni uzaytirish uchun {ADMIN_USERNAME} bilan bog'laning."

    await message.answer(text, reply_markup=subscription_kb(True), parse_mode="HTML")


# ──────────────────────────────────────────────────────────────
# Change tariff
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sub:change")
async def change_tariff(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "📋 <b>Tarifni tanlang:</b>",
        reply_markup=tariff_kb(TARIFFS),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "tariff:back")
async def tariff_back(cb: CallbackQuery, session: AsyncSession) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
    active_count = len(list(await session.scalars(
        select(Announcement).where(
            Announcement.user_id == user.id,
            Announcement.is_active == True,
        )
    )))
    accounts = list(await session.scalars(
        select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True,
        )
    ))
    text = (
        "💎 <b>Obunalarim</b>\n\n"
        f"📊 Aktiv xabarlar: {active_count} ta\n"
        f"📱 Akkauntlar: {len(accounts)} ta\n"
        f"💳 Tarif: {_trial_status(user)}\n"
        f"📅 Boshlandi: {_fmt_date(user.created_at)}\n"
        f"📅 Tugadi: {_fmt_date(user.trial_expires_at)}\n"
    )
    await cb.message.edit_text(text, reply_markup=subscription_kb(True), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("tariff:"))
async def select_tariff(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[1]
    if key == "back":
        return  # handled above

    if key not in TARIFFS:
        await cb.answer("Noto'g'ri tarif.", show_alert=True)
        return

    name, price, days = TARIFFS[key]
    await state.set_state(SubFSM.waiting_receipt)
    await state.update_data(tariff_key=key, tariff_name=name, tariff_price=price)

    await cb.message.edit_text(
        f"💳 <b>{name} tarifi — {price:,} so'm</b>\n\n".replace(",", " ") +
        f"🏦 To'lov kartasi: <code>{PAYMENT_CARD}</code>\n"
        f"👤 Kartaning egasi: {CARD_OWNER}\n\n"
        f"Iltimos, ushbu tarif uchun to'lov kvitansiyasini yuboring.",
        reply_markup=cancel_payment_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Extend subscription (same payment flow)
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sub:extend")
async def extend_sub(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SubFSM.waiting_receipt)
    await state.update_data(tariff_key=None, tariff_name="Uzaytirish", tariff_price=0)

    await cb.message.edit_text(
        f"💳 <b>Obunani uzaytirish</b>\n\n"
        f"🏦 To'lov kartasi: <code>{PAYMENT_CARD}</code>\n"
        f"👤 Kartaning egasi: {CARD_OWNER}\n\n"
        f"Iltimos, ushbu tarif uchun to'lov kvitansiyasini yuboring.",
        reply_markup=cancel_payment_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "sub:back")
async def sub_back(cb: CallbackQuery) -> None:
    await cb.message.answer("Asosiy menyu:", reply_markup=main_menu())
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Receipt
# ──────────────────────────────────────────────────────────────

@router.callback_query(SubFSM.waiting_receipt, F.data == "pay:cancel")
async def cancel_payment(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ Bekor qilindi.")
    await cb.message.answer("Asosiy menyu:", reply_markup=main_menu())
    await cb.answer()


@router.message(SubFSM.waiting_receipt, F.photo)
async def receive_receipt(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))

    # Forward receipt to admins
    for admin_id in ADMIN_IDS:
        try:
            tariff_info = f"Tarif: {data.get('tariff_name', '?')} — {data.get('tariff_price', 0):,} so'm".replace(",", " ")
            caption = (
                f"💳 <b>Yangi to'lov kvitansiyasi!</b>\n\n"
                f"👤 Foydalanuvchi: {message.from_user.full_name}\n"
                f"📱 ID: <code>{message.from_user.id}</code>\n"
                f"📞 Telefon: +{user.phone if user else '?'}\n"
                f"🏷 {tariff_info}"
            )
            await message.bot.send_photo(
                admin_id,
                photo=message.photo[-1].file_id,
                caption=caption,
                parse_mode="HTML",
            )
        except Exception:
            pass

    await state.clear()
    await message.answer(
        "✅ <b>Kvitansiya yuborildi!</b>\n\n"
        "Administrator tekshiruidan so'ng obunangiz faollashtiriladi.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


@router.message(SubFSM.waiting_receipt, F.text == "❌ Bekor qilish")
async def receipt_cancel_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu())


@router.message(SubFSM.waiting_receipt, ~F.photo)
async def receipt_not_photo(message: Message) -> None:
    await message.answer(
        "⚠️ Iltimos, to'lov kvitansiyasining rasmini yuboring.\n\n"
        "Yoki /start bosib menyuga qayting."
    )

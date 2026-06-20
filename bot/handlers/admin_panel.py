"""
Telegram-based admin panel.
Only accessible by user IDs listed in ADMIN_IDS.

Commands:
  /admin → opens admin menu

Menu:
  📊 Statistikalar   → stats
  👤 Foydalanuvchilar → last 10 users + search
  ➕ Obuna berish     → give subscription to a user
  📋 To'lovlar        → pending payment requests
  ◀️ Orqaga          → close
"""

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_IDS
from database.models import (
    Announcement, AnnouncementStatus,
    PaymentRequest, TelegramAccount, User,
)

router = Router()


class AdminFSM(StatesGroup):
    waiting_user_id  = State()
    waiting_days     = State()
    waiting_message  = State()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def admin_main_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📊 Statistikalar",    callback_data="adm:stats")
    b.button(text="👤 Foydalanuvchilar", callback_data="adm:users")
    b.button(text="➕ Obuna berish",      callback_data="adm:give")
    b.button(text="💳 To'lovlar",         callback_data="adm:pays")
    b.button(text="◀️ Yopish",           callback_data="adm:close")
    b.adjust(1)
    return b.as_markup()


def back_kb():
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Orqaga", callback_data="adm:main")
    b.adjust(1)
    return b.as_markup()


def _user_status(u: User) -> str:
    now = datetime.utcnow()
    if u.is_premium:
        return "💎"
    if u.trial_expires_at and u.trial_expires_at > now:
        return "🎁"
    return "❌"


# ──────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def admin_cmd(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🔐 <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=admin_main_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:main")
async def adm_main(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        return
    await cb.message.edit_text(
        "🔐 <b>Admin Panel</b>\n\nQuyidagi bo'limlardan birini tanlang:",
        reply_markup=admin_main_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "adm:close")
async def adm_close(cb: CallbackQuery) -> None:
    await cb.message.delete()
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    now = datetime.utcnow()

    total   = (await session.scalar(select(func.count(User.id)))) or 0
    premium = (await session.scalar(select(func.count(User.id)).where(User.is_premium == True))) or 0
    trial   = (await session.scalar(select(func.count(User.id)).where(
        User.is_premium == False, User.trial_expires_at > now,
    ))) or 0
    expired = total - premium - trial

    ann_total  = (await session.scalar(select(func.count(Announcement.id)))) or 0
    ann_active = (await session.scalar(select(func.count(Announcement.id)).where(
        Announcement.is_active == True,
        Announcement.status == AnnouncementStatus.scheduled,
    ))) or 0
    pending_pay = (await session.scalar(select(func.count(PaymentRequest.id)).where(
        PaymentRequest.status == "pending"
    ))) or 0

    await cb.message.edit_text(
        "📊 <b>Statistikalar</b>\n\n"
        f"👥 Jami foydalanuvchi: <b>{total}</b>\n"
        f"💎 Premium: <b>{premium}</b>\n"
        f"🎁 Sinov muddatida: <b>{trial}</b>\n"
        f"❌ Muddati tugagan: <b>{expired}</b>\n\n"
        f"📨 Jami xabarlar: <b>{ann_total}</b>\n"
        f"🟢 Aktiv xabarlar: <b>{ann_active}</b>\n\n"
        f"💳 Kutilayotgan to'lovlar: <b>{pending_pay}</b>",
        reply_markup=back_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Users list
# ──────────────────────────────────────────────────────────────

PAGE_SIZE = 20


@router.callback_query(F.data == "adm:users")
async def adm_users(cb: CallbackQuery, session: AsyncSession) -> None:
    await _show_users_page(cb, session, page=0)


@router.callback_query(F.data.startswith("adm:users:"))
async def adm_users_page(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    page = int(cb.data.split(":")[2])
    await _show_users_page(cb, session, page)


async def _show_users_page(cb: CallbackQuery, session: AsyncSession, page: int) -> None:
    if not is_admin(cb.from_user.id):
        return

    total = (await session.scalar(select(func.count(User.id)))) or 0
    users = list(await session.scalars(
        select(User).order_by(User.created_at.desc())
        .offset(page * PAGE_SIZE).limit(PAGE_SIZE)
    ))

    lines = [f"👤 <b>Foydalanuvchilar ({total} ta) — sahifa {page + 1}:</b>\n"]
    for u in users:
        exp = u.trial_expires_at.strftime('%d.%m.%y') if u.trial_expires_at else '—'
        lines.append(
            f"{_user_status(u)} <code>{u.telegram_id}</code> "
            f"— {u.full_name or '—'} | +{u.phone or '?'} | {exp}"
        )

    b = InlineKeyboardBuilder()
    for u in users:
        b.button(
            text=f"✉️ {u.full_name or str(u.telegram_id)}",
            callback_data=f"adm:msg:{u.telegram_id}",
        )
    b.adjust(2)

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="◀️ Oldingi", callback_data=f"adm:users:{page - 1}")
    if (page + 1) * PAGE_SIZE < total:
        nav.button(text="Keyingi ▶️", callback_data=f"adm:users:{page + 1}")
    nav.button(text="🏠 Orqaga", callback_data="adm:main")
    nav.adjust(2)

    b.attach(nav)

    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:msg:"))
async def adm_msg_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    target_id = int(cb.data.split(":")[2])
    await state.set_state(AdminFSM.waiting_message)
    await state.update_data(target_tg_id=target_id)
    await cb.message.answer(
        f"✉️ <b>Foydalanuvchiga xabar yuborish</b>\n\n"
        f"ID: <code>{target_id}</code>\n\n"
        "Xabaringizni yozing:",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(AdminFSM.waiting_message)
async def adm_msg_send(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    target_tg_id = data["target_tg_id"]
    await state.clear()
    try:
        await message.bot.send_message(
            target_tg_id,
            f"📩 <b>Admin xabari:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer("✅ Xabar muvaffaqiyatli yuborildi!")
    except Exception as e:
        await message.answer(f"❌ Xabar yuborishda xatolik: {e}")


# ──────────────────────────────────────────────────────────────
# Give subscription
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:give")
async def adm_give_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminFSM.waiting_user_id)
    await cb.message.answer(
        "➕ <b>Obuna berish</b>\n\n"
        "Foydalanuvchining Telegram ID yoki telefon raqamini kiriting:\n"
        "<i>Masalan: 123456789 yoki +998901234567</i>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(AdminFSM.waiting_user_id)
async def adm_give_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return

    q = message.text.strip()
    user = None

    digits = q.lstrip("+")
    if digits.isdigit():
        if len(digits) >= 11:  # phone
            user = await session.scalar(select(User).where(User.phone == digits))
        else:                   # telegram id
            user = await session.scalar(select(User).where(User.telegram_id == int(digits)))

    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi. Qaytadan kiriting:")
        return

    now = datetime.utcnow()
    await state.update_data(uid=user.id, tg_id=user.telegram_id, name=user.full_name or "—")
    await state.set_state(AdminFSM.waiting_days)

    b = InlineKeyboardBuilder()
    for days, lbl in [(1,"1 kun"),(7,"7 kun"),(30,"1 oy"),(90,"3 oy"),(180,"6 oy"),(365,"1 yil")]:
        b.button(text=lbl, callback_data=f"adm:d:{days}")
    b.button(text="❌ Bekor", callback_data="adm:cancel_give")
    b.adjust(3)

    exp = user.trial_expires_at.strftime('%d.%m.%Y %H:%M') if user.trial_expires_at else '—'
    await message.answer(
        f"✅ Topildi: <b>{user.full_name or '—'}</b>\n"
        f"📱 Telefon: +{user.phone or '?'}\n"
        f"📅 Joriy tugash: {exp}\n"
        f"Holat: {_user_status(user)}\n\n"
        "Necha kun obuna berish?",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm:d:"), AdminFSM.waiting_days)
async def adm_give_days(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    days = int(cb.data.split(":")[2])
    data = await state.get_data()
    await state.clear()

    user = await session.get(User, data["uid"])
    if user:
        user.is_premium = True
        base = max(user.trial_expires_at or datetime.utcnow(), datetime.utcnow())
        user.trial_expires_at = base + timedelta(days=days)
        await session.commit()

        # Notify user in Telegram
        try:
            await cb.bot.send_message(
                data["tg_id"],
                f"🎉 <b>Tabriklaymiz!</b>\n\n"
                f"Sizga <b>{days} kunlik</b> premium obuna berildi!\n"
                f"📅 Tugash sanasi: {user.trial_expires_at.strftime('%d.%m.%Y')}\n\n"
                f"Endi barcha funksiyalardan to'liq foydalanishingiz mumkin! 🚀",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await cb.message.edit_text(
        f"✅ <b>{data['name']}</b> ga <b>{days} kun</b> obuna berildi!",
        reply_markup=None,
        parse_mode="HTML",
    )
    await cb.answer("✅ Obuna berildi!")


@router.callback_query(F.data == "adm:cancel_give")
async def adm_cancel_give(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ Bekor qilindi.", reply_markup=None)
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Pending payments
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:pays")
async def adm_pays(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return

    pays = list(await session.scalars(
        select(PaymentRequest)
        .where(PaymentRequest.status == "pending")
        .order_by(PaymentRequest.created_at.desc())
        .limit(10)
    ))

    if not pays:
        await cb.message.edit_text(
            "💳 Kutilayotgan to'lovlar yo'q.",
            reply_markup=back_kb(),
            parse_mode="HTML",
        )
        await cb.answer()
        return

    b = InlineKeyboardBuilder()
    for p in pays:
        user = await session.get(User, p.user_id)
        name = user.full_name if user else "?"
        b.button(
            text=f"✅ #{p.id} — {name} ({p.tariff_name})",
            callback_data=f"adm:pay_approve:{p.id}",
        )
        b.button(text=f"❌ Rad #{p.id}", callback_data=f"adm:pay_reject:{p.id}")
    b.button(text="◀️ Orqaga", callback_data="adm:main")
    b.adjust(2)

    await cb.message.edit_text(
        f"💳 <b>Kutilayotgan to'lovlar ({len(pays)} ta):</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:pay_approve:"))
async def adm_pay_approve(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    pay_id = int(cb.data.split(":")[2])
    pr = await session.get(PaymentRequest, pay_id)
    if pr:
        pr.status = "approved"
        pr.processed_at = datetime.utcnow()
        user = await session.get(User, pr.user_id)
        if user:
            tariff_days = {"1_oy": 30, "3_oy": 90, "6_oy": 180}.get(pr.tariff_key or "", 30)
            user.is_premium = True
            base = max(user.trial_expires_at or datetime.utcnow(), datetime.utcnow())
            user.trial_expires_at = base + timedelta(days=tariff_days)
            await session.commit()
            try:
                await cb.bot.send_message(
                    user.telegram_id,
                    f"✅ <b>To'lovingiz tasdiqlandi!</b>\n\n"
                    f"Sizga {tariff_days} kunlik premium obuna berildi!\n"
                    f"📅 Tugash: {user.trial_expires_at.strftime('%d.%m.%Y')}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
    await cb.answer("✅ Tasdiqlandi!")
    await adm_pays(cb, session)


@router.callback_query(F.data.startswith("adm:pay_reject:"))
async def adm_pay_reject(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    pay_id = int(cb.data.split(":")[2])
    pr = await session.get(PaymentRequest, pay_id)
    if pr:
        pr.status = "rejected"
        pr.processed_at = datetime.utcnow()
        await session.commit()
    await cb.answer("❌ Rad etildi!")
    await adm_pays(cb, session)

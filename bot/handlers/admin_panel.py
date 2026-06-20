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
PAGE_SIZE = 20


class AdminFSM(StatesGroup):
    waiting_user_id = State()
    waiting_message = State()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def _status(u: User) -> str:
    now = datetime.utcnow()
    if u.is_premium:
        return "💎 Premium"
    if u.trial_expires_at and u.trial_expires_at > now:
        remaining = (u.trial_expires_at - now).total_seconds() / 3600
        return f"🎁 Sinov ({remaining:.0f}s)"
    return "❌ Muddati tugagan"


def _status_icon(u: User) -> str:
    now = datetime.utcnow()
    if u.is_premium:
        return "💎"
    if u.trial_expires_at and u.trial_expires_at > now:
        return "🎁"
    return "❌"


def admin_main_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📊 Statistikalar",    callback_data="adm:stats")
    b.button(text="👤 Foydalanuvchilar", callback_data="adm:users:0")
    b.button(text="💳 To'lovlar",        callback_data="adm:pays")
    b.button(text="◀️ Yopish",          callback_data="adm:close")
    b.adjust(1)
    return b.as_markup()


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
async def adm_main(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
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

    ann_active = (await session.scalar(select(func.count(Announcement.id)).where(
        Announcement.is_active == True,
        Announcement.status == AnnouncementStatus.scheduled,
    ))) or 0
    pending_pay = (await session.scalar(select(func.count(PaymentRequest.id)).where(
        PaymentRequest.status == "pending"
    ))) or 0

    b = InlineKeyboardBuilder()
    b.button(text="◀️ Orqaga", callback_data="adm:main")

    await cb.message.edit_text(
        "📊 <b>Statistikalar</b>\n\n"
        f"👥 Jami foydalanuvchi: <b>{total}</b>\n"
        f"💎 Premium: <b>{premium}</b>\n"
        f"🎁 Sinov muddatida: <b>{trial}</b>\n"
        f"❌ Muddati tugagan: <b>{expired}</b>\n\n"
        f"🟢 Aktiv e'lonlar: <b>{ann_active}</b>\n"
        f"💳 Kutilayotgan to'lovlar: <b>{pending_pay}</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Users list (paginated)
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:users:"))
async def adm_users(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    page = int(cb.data.split(":")[2])

    total = (await session.scalar(select(func.count(User.id)))) or 0
    users = list(await session.scalars(
        select(User).order_by(User.created_at.desc())
        .offset(page * PAGE_SIZE).limit(PAGE_SIZE)
    ))

    lines = [f"👤 <b>Foydalanuvchilar ({total} ta) — sahifa {page + 1}:</b>\n"]
    for u in users:
        exp = u.trial_expires_at.strftime('%d.%m.%y') if u.trial_expires_at else '—'
        lines.append(
            f"{_status_icon(u)} <code>{u.telegram_id}</code> "
            f"— {u.full_name or '—'} | {exp}"
        )

    b = InlineKeyboardBuilder()
    for u in users:
        b.button(
            text=f"{_status_icon(u)} {u.full_name or str(u.telegram_id)}",
            callback_data=f"adm:user:{u.telegram_id}:{page}",
        )
    b.adjust(2)

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="◀️ Oldingi", callback_data=f"adm:users:{page - 1}")
    if (page + 1) * PAGE_SIZE < total:
        nav.button(text="Keyingi ▶️", callback_data=f"adm:users:{page + 1}")
    nav.button(text="🏠 Bosh menyu", callback_data="adm:main")
    nav.adjust(2)

    b.attach(nav)
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup(), parse_mode="HTML")
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# User detail page
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:user:"))
async def adm_user_detail(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    tg_id = int(parts[2])
    page  = int(parts[3]) if len(parts) > 3 else 0

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user:
        await cb.answer("Foydalanuvchi topilmadi!", show_alert=True)
        return

    exp = user.trial_expires_at.strftime('%d.%m.%Y') if user.trial_expires_at else '—'
    acc_count = (await session.scalar(
        select(func.count(TelegramAccount.id)).where(TelegramAccount.user_id == user.id)
    )) or 0
    ann_count = (await session.scalar(
        select(func.count(Announcement.id)).where(Announcement.user_id == user.id)
    )) or 0

    b = InlineKeyboardBuilder()
    b.button(text="💎 Obuna berish",    callback_data=f"adm:sub:{tg_id}:{page}")
    b.button(text="✉️ Xabar yuborish",  callback_data=f"adm:msg:{tg_id}:{page}")
    b.button(text="🚫 Bloklash" if user.is_active else "✅ Blokdan chiqarish",
             callback_data=f"adm:block:{tg_id}:{page}")
    b.button(text="◀️ Orqaga",          callback_data=f"adm:users:{page}")
    b.adjust(2)

    await cb.message.edit_text(
        f"👤 <b>Foydalanuvchi profili</b>\n\n"
        f"📛 Ism: <b>{user.full_name or '—'}</b>\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"📱 Telefon: +{user.phone or '?'}\n"
        f"📊 Holat: <b>{_status(user)}</b>\n"
        f"📅 Tugash: <b>{exp}</b>\n"
        f"📱 Akkauntlar: <b>{acc_count} ta</b>\n"
        f"📨 E'lonlar: <b>{ann_count} ta</b>\n"
        f"🗓 Ro'yxatdan: <b>{user.created_at.strftime('%d.%m.%Y')}</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Give subscription (from user detail — no FSM needed)
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:sub:"))
async def adm_sub_pick(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    tg_id = int(parts[2])
    page  = int(parts[3]) if len(parts) > 3 else 0

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user:
        await cb.answer("Topilmadi!", show_alert=True)
        return

    b = InlineKeyboardBuilder()
    for days, lbl in [(1,"1 kun"),(7,"7 kun"),(30,"1 oy"),(90,"3 oy"),(180,"6 oy"),(365,"1 yil")]:
        b.button(text=lbl, callback_data=f"adm:subgive:{tg_id}:{days}:{page}")
    b.button(text="◀️ Orqaga", callback_data=f"adm:user:{tg_id}:{page}")
    b.adjust(3)

    exp = user.trial_expires_at.strftime('%d.%m.%Y') if user.trial_expires_at else '—'
    await cb.message.edit_text(
        f"💎 <b>Obuna berish</b>\n\n"
        f"👤 {user.full_name or '—'}\n"
        f"📅 Hozirgi tugash: <b>{exp}</b>\n"
        f"Holat: {_status(user)}\n\n"
        "Necha kun obuna berish?",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subgive:"))
async def adm_subgive(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    tg_id = int(parts[2])
    days  = int(parts[3])
    page  = int(parts[4]) if len(parts) > 4 else 0

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user:
        await cb.answer("Topilmadi!", show_alert=True)
        return

    user.is_premium = True
    base = max(user.trial_expires_at or datetime.utcnow(), datetime.utcnow())
    user.trial_expires_at = base + timedelta(days=days)
    await session.commit()

    try:
        await cb.bot.send_message(
            tg_id,
            f"🎉 <b>Tabriklaymiz!</b>\n\n"
            f"Sizga <b>{days} kunlik</b> premium obuna berildi!\n"
            f"📅 Tugash sanasi: {user.trial_expires_at.strftime('%d.%m.%Y')}\n\n"
            f"Endi barcha funksiyalardan to'liq foydalanishingiz mumkin! 🚀",
            parse_mode="HTML",
        )
    except Exception:
        pass

    await cb.answer(f"✅ {days} kun obuna berildi!", show_alert=True)
    cb.data = f"adm:user:{tg_id}:{page}"
    await adm_user_detail(cb, session)


# ──────────────────────────────────────────────────────────────
# Message user
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:msg:"))
async def adm_msg_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    tg_id = int(parts[2])
    page  = int(parts[3]) if len(parts) > 3 else 0

    await state.set_state(AdminFSM.waiting_message)
    await state.update_data(target_tg_id=tg_id, back_page=page)
    await cb.message.answer(
        f"✉️ <b>Foydalanuvchiga xabar</b>\n\n"
        f"ID: <code>{tg_id}</code>\n\n"
        "Xabaringizni yozing (bekor qilish: /admin):",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(AdminFSM.waiting_message)
async def adm_msg_send(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    await state.clear()
    try:
        await message.bot.send_message(
            data["target_tg_id"],
            f"📩 <b>Admin xabari:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer("✅ Xabar muvaffaqiyatli yuborildi!")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


# ──────────────────────────────────────────────────────────────
# Block / Unblock user
# ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:block:"))
async def adm_block(cb: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    tg_id = int(parts[2])
    page  = int(parts[3]) if len(parts) > 3 else 0

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user:
        await cb.answer("Topilmadi!", show_alert=True)
        return

    user.is_active = not user.is_active
    await session.commit()

    status_text = "bloklandi" if not user.is_active else "blokdan chiqarildi"
    await cb.answer(f"✅ Foydalanuvchi {status_text}!", show_alert=True)
    cb.data = f"adm:user:{tg_id}:{page}"
    await adm_user_detail(cb, session)


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
        .limit(20)
    ))

    if not pays:
        b = InlineKeyboardBuilder()
        b.button(text="◀️ Orqaga", callback_data="adm:main")
        await cb.message.edit_text(
            "💳 Kutilayotgan to'lovlar yo'q.",
            reply_markup=b.as_markup(),
        )
        await cb.answer()
        return

    b = InlineKeyboardBuilder()
    for p in pays:
        user = await session.get(User, p.user_id)
        name = (user.full_name if user else None) or "?"
        b.button(
            text=f"✅ {name} — {p.tariff_name or '?'}",
            callback_data=f"adm:pay_approve:{p.id}",
        )
        b.button(text=f"❌ Rad", callback_data=f"adm:pay_reject:{p.id}")
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
        user = await session.get(User, pr.user_id)
        if user:
            try:
                await cb.bot.send_message(
                    user.telegram_id,
                    "❌ <b>To'lovingiz rad etildi.</b>\n\n"
                    "Savol bo'lsa admin bilan bog'laning.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
    await cb.answer("❌ Rad etildi!")
    await adm_pays(cb, session)

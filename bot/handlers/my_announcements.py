"""
"Mening xabarlari" — shows scheduled announcement cards with controls.

Each card:
  📩 Xabar #N
  🖼/📝 Xabar turi: ...
  📄 Xabar matni: ...
  📱 Akkount: +...
  ⏰ Oraliq: har N daqiqa/soat
  🕐 Keyingi yuborish: ...
  📤 Oxirgi yuborilgan: ...
  📊 Holat: Rejalashtirilgan / To'xtatilgan
  📅 Yaratilgan: ...
  👥 Guruhlar: N ta

Buttons: To'xtatish/Davom ettirish | O'chirish | Matnni o'zgartirish | Orqaga
"""

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Announcement, AnnouncementGroup, AnnouncementSend,
    AnnouncementStatus, MessageType, TelegramAccount, User,
)
from bot.handlers.announcement import AnnounceFSM
from bot.keyboards.inline import announcement_card_kb
from bot.keyboards.reply import cancel_only, main_menu

router = Router()


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    if not dt:
        return "Hali yuborilmagan"
    return dt.strftime("%Y-%m-%d %H:%M")


def _interval_str(minutes: int) -> str:
    if minutes < 60:
        return f"har {minutes} daqiqada"
    h = minutes // 60
    return f"har {h} soatda"


def _card_text(ann: Announcement, group_count: int, account_phone: str) -> str:
    tur = "rasm + matn" if ann.message_type == MessageType.photo else "matn"
    icon = "🖼" if ann.message_type == MessageType.photo else "📝"
    holat = "Rejalashtirilgan" if ann.status == AnnouncementStatus.scheduled else "To'xtatilgan"
    holat_icon = "🟢" if ann.status == AnnouncementStatus.scheduled else "🔴"

    text_preview = (ann.text[:120] + "...") if len(ann.text) > 120 else ann.text

    return (
        f"📩 <b>Xabar #{ann.id}</b>\n\n"
        f"{icon} Xabar turi: {tur}\n"
        f"📄 Xabar matni:\n<code>{text_preview}</code>\n\n"
        f"📱 Akkount: +{account_phone}\n"
        f"⏰ Oraliq: {_interval_str(ann.interval_minutes)}\n"
        f"🕐 Keyingi yuborish: {_fmt_dt(ann.next_send_at)}\n"
        f"📤 Oxirgi yuborilgan: {_fmt_dt(ann.last_sent_at)}\n"
        f"{holat_icon} Holat: {holat}\n"
        f"📅 Yaratilgan: {_fmt_dt(ann.created_at)}\n"
        f"👥 Guruhlar: {group_count} ta"
    )


# ──────────────────────────────────────────────────────────────
# List
# ──────────────────────────────────────────────────────────────

@router.message(F.text == "📋 Mening elonlarim")
async def my_announcements(message: Message, session: AsyncSession) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("⚠️ Avval /start orqali ro'yxatdan o'ting!")
        return

    anns = list(await session.scalars(
        select(Announcement)
        .where(Announcement.user_id == user.id)
        .order_by(Announcement.created_at.desc())
        .limit(10)
    ))

    if not anns:
        await message.answer("📭 Siz hali hech qanday xabar rejalashtirilmagan.")
        return

    await message.answer(f"📋 <b>Xabarlaringiz ({len(anns)} ta):</b>", parse_mode="HTML")

    for ann in anns:
        account = await session.get(TelegramAccount, ann.account_id)
        phone = account.phone if account else "noma'lum"

        group_count = len(list(await session.scalars(
            select(AnnouncementGroup).where(AnnouncementGroup.announcement_id == ann.id)
        )))

        await message.answer(
            _card_text(ann, group_count, phone),
            parse_mode="HTML",
            reply_markup=announcement_card_kb(ann.id, ann.is_active),
        )


# ──────────────────────────────────────────────────────────────
# Card actions
# ──────────────────────────────────────────────────────────────

async def _get_ann_for_user(cb: CallbackQuery, ann_id: int, session: AsyncSession):
    user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
    ann = await session.scalar(
        select(Announcement).where(
            Announcement.id == ann_id,
            Announcement.user_id == user.id,
        )
    )
    return ann


@router.callback_query(F.data.startswith("ann:stop:"))
async def stop_announcement(cb: CallbackQuery, session: AsyncSession) -> None:
    ann_id = int(cb.data.split(":")[2])
    ann = await _get_ann_for_user(cb, ann_id, session)
    if not ann:
        await cb.answer("E'lon topilmadi.", show_alert=True)
        return

    ann.is_active = False
    ann.status = AnnouncementStatus.stopped
    await session.commit()

    account = await session.get(TelegramAccount, ann.account_id)
    phone = account.phone if account else "noma'lum"
    group_count = len(list(await session.scalars(
        select(AnnouncementGroup).where(AnnouncementGroup.announcement_id == ann.id)
    )))

    await cb.message.edit_text(
        _card_text(ann, group_count, phone),
        parse_mode="HTML",
        reply_markup=announcement_card_kb(ann.id, ann.is_active),
    )
    await cb.answer("⏸ To'xtatildi.")


@router.callback_query(F.data.startswith("ann:resume:"))
async def resume_announcement(cb: CallbackQuery, session: AsyncSession) -> None:
    ann_id = int(cb.data.split(":")[2])
    ann = await _get_ann_for_user(cb, ann_id, session)
    if not ann:
        await cb.answer("E'lon topilmadi.", show_alert=True)
        return

    ann.is_active = True
    ann.status = AnnouncementStatus.scheduled
    # Schedule next send immediately
    ann.next_send_at = datetime.utcnow()
    await session.commit()

    account = await session.get(TelegramAccount, ann.account_id)
    phone = account.phone if account else "noma'lum"
    group_count = len(list(await session.scalars(
        select(AnnouncementGroup).where(AnnouncementGroup.announcement_id == ann.id)
    )))

    await cb.message.edit_text(
        _card_text(ann, group_count, phone),
        parse_mode="HTML",
        reply_markup=announcement_card_kb(ann.id, ann.is_active),
    )
    await cb.answer("▶️ Davom ettirildi.")


@router.callback_query(F.data.startswith("ann:del:"))
async def delete_announcement(cb: CallbackQuery, session: AsyncSession) -> None:
    ann_id = int(cb.data.split(":")[2])
    ann = await _get_ann_for_user(cb, ann_id, session)
    if not ann:
        await cb.answer("E'lon topilmadi.", show_alert=True)
        return

    await session.execute(delete(AnnouncementSend).where(AnnouncementSend.announcement_id == ann_id))
    await session.execute(delete(AnnouncementGroup).where(AnnouncementGroup.announcement_id == ann_id))
    await session.delete(ann)
    await session.commit()

    await cb.message.edit_text(f"🗑 <b>Xabar #{ann_id} o'chirildi.</b>", parse_mode="HTML")
    await cb.answer("O'chirildi.")


@router.callback_query(F.data.startswith("ann:edit:"))
async def edit_announcement(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    ann_id = int(cb.data.split(":")[2])
    ann = await _get_ann_for_user(cb, ann_id, session)
    if not ann:
        await cb.answer("E'lon topilmadi.", show_alert=True)
        return

    await state.set_state(AnnounceFSM.edit_text)
    await state.update_data(edit_ann_id=ann_id)

    await cb.message.answer(
        "✏️ <b>Yangi xabarni yuboring:</b>\n\n"
        "Oddiy matn yoki rasm + caption yuborishingiz mumkin.\n"
        "Captionsiz rasmlar qabul qilinmaydi.",
        reply_markup=cancel_only(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "ann:back")
async def back_from_card(cb: CallbackQuery) -> None:
    await cb.message.answer("Asosiy menyu:", reply_markup=main_menu())
    await cb.answer()

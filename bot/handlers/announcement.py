"""
Announcement flow matching the reference bot screenshots:

1. "📨 Xabar yuborish" → shows instructions
2. User sends TEXT or PHOTO+CAPTION (captionless photo rejected)
3. Group selection inline keyboard (✅/❌ per group, count header)
4. Interval selection (5 daqiqa … 24 soat)
5. Save to DB, send immediately via Telethon, schedule repeats
"""

import asyncio
import io
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import SEND_DELAY
from database.models import (
    Announcement, AnnouncementGroup, AnnouncementSend,
    AnnouncementStatus, Group, MessageType,
    TelegramAccount, User,
)
from userbot import manager
from bot.keyboards.inline import groups_keyboard, interval_keyboard, interval_label
from bot.keyboards.reply import cancel_only, main_menu

logger = logging.getLogger(__name__)

router = Router()

CANCEL = "❌ Bekor qilish"


class AnnounceFSM(StatesGroup):
    waiting_message = State()   # user sends text / photo+caption
    select_groups   = State()   # inline group checkboxes
    select_interval = State()   # inline interval picker
    edit_text       = State()   # "Matnni o'zgartirish" sub-flow


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _is_active(user: User) -> bool:
    if user.is_premium:
        return True
    return bool(user.trial_expires_at and user.trial_expires_at > datetime.utcnow())


def _groups_header(total: int, selected: int) -> str:
    return (
        "📊 <b>Guruhlarni tanlash</b>\n\n"
        f"📍 Jami guruhlar: {total}\n"
        f"✅ Tanlangan: {selected}\n\n"
        "Xabar yubormoqchi bo'lgan guruhlaringizni tanlang:"
    )


async def _get_user_groups(user: User, session: AsyncSession) -> list[dict]:
    accounts = list(await session.scalars(
        select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True,
        )
    ))
    groups: list[dict] = []
    for acc in accounts:
        gs = await session.scalars(select(Group).where(Group.account_id == acc.id))
        groups.extend({"id": g.id, "title": g.title} for g in gs)
    return groups


async def _send_announcement_now(ann: Announcement, session: AsyncSession) -> tuple[int, int]:
    """Send to all target groups. Returns (ok_count, fail_count)."""
    account = await session.get(TelegramAccount, ann.account_id)
    if not account:
        return 0, 0

    try:
        client = await manager.get_client(account.id, account.session_string)
    except Exception as e:
        logger.error("Cannot get client for account %s: %s", account.id, e)
        return 0, 0

    links = list(await session.scalars(
        select(AnnouncementGroup).where(AnnouncementGroup.announcement_id == ann.id)
    ))

    photo_bytes = None  # io.BytesIO or None
    if ann.photo_file_id:
        # photo_file_id stored as raw bytes (downloaded once during creation)
        # We re-download using the stored file_id via bot later;
        # here we just pass None — actual download happens in the caller
        pass

    ok = fail = 0
    for link in links:
        group = await session.get(Group, link.group_id)
        if not group:
            continue
        try:
            msg_id = await manager.send_to_group(
                client, group.chat_id, ann.text,
                photo=None,  # photo handled separately when file_id available
            )
            session.add(AnnouncementSend(
                announcement_id=ann.id,
                group_id=group.id,
                message_id=msg_id,
                status="sent",
                sent_at=datetime.utcnow(),
            ))
            ok += 1
        except Exception as e:
            session.add(AnnouncementSend(
                announcement_id=ann.id,
                group_id=group.id,
                status="failed",
                error=str(e)[:200],
            ))
            fail += 1
            logger.warning("Send failed to group %s: %s", group.chat_id, e)

        await asyncio.sleep(SEND_DELAY)

    return ok, fail


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

@router.message(F.text == "📨 Elon berish")
async def start_announce(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("⚠️ Avval /start orqali ro'yxatdan o'ting!")
        return
    if not _is_active(user):
        from config import ADMIN_USERNAME
        await message.answer(
            f"❌ Sinov muddatingiz tugagan.\n"
            f"Obuna uchun {ADMIN_USERNAME} bilan bog'laning."
        )
        return

    account = await session.scalar(
        select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True,
        )
    )
    if not account:
        await message.answer(
            "❌ <b>Akkaunt topilmadi</b>\n\n"
            "Xabar yuborish uchun avval Telegram akkaunt qo'shishingiz kerak.\n\n"
            "'➕ Akkaunt qo'shish' tugmasidan foydalaning!",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )
        return

    await state.set_state(AnnounceFSM.waiting_message)
    await message.answer(
        "📨 <b>Xabar yaratish</b>\n\n"
        "Guruhlarga yubormoqchi bo'lgan xabaringizni yuboring.\n\n"
        "Siz yuborishingiz mumkin:\n"
        "• 📝 Oddiy matn xabar\n"
        "• 🖼 Rasm + caption (izoh)\n\n"
        "⚠️ <b>Diqqat:</b>\n"
        "Rasm yuborishingiz zarur bo'lsa, caption (izoh) yozish MAJBURIY\n"
        "Captionsiz rasmlar qabul qilinmaydi",
        reply_markup=cancel_only(),
        parse_mode="HTML",
    )


# ──────────────────────────────────────────────────────────────
# Receive message (text or photo+caption)
# ──────────────────────────────────────────────────────────────

@router.message(AnnounceFSM.waiting_message, F.text == CANCEL)
async def cancel_waiting(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu())


@router.message(AnnounceFSM.waiting_message, F.photo)
async def receive_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.caption or not message.caption.strip():
        await message.answer(
            "⚠️ Captionsiz rasmlar qabul qilinmaydi!\n\n"
            "Rasmni caption (izoh) bilan qayta yuboring."
        )
        return

    file_id = message.photo[-1].file_id
    await state.update_data(
        msg_type="photo",
        text=message.caption.strip(),
        photo_file_id=file_id,
    )
    await _show_groups(message, state, session)


@router.message(AnnounceFSM.waiting_message, F.text)
async def receive_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text == CANCEL:
        return  # handled above

    await state.update_data(
        msg_type="text",
        text=message.text.strip(),
        photo_file_id=None,
    )
    await _show_groups(message, state, session)


# ──────────────────────────────────────────────────────────────
# Group selection
# ──────────────────────────────────────────────────────────────

async def _show_groups(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    groups = await _get_user_groups(user, session)

    if not groups:
        await message.answer(
            "⚠️ Guruhlar topilmadi.\nAvval '➕ Akkaunt qo'shish' orqali akkaunt qo'shing.",
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    await state.update_data(groups=groups, selected=[])
    await state.set_state(AnnounceFSM.select_groups)

    await message.answer(
        _groups_header(len(groups), 0),
        reply_markup=groups_keyboard(groups, []),
        parse_mode="HTML",
    )


@router.callback_query(AnnounceFSM.select_groups, F.data.startswith("grp:t:"))
async def toggle_group(cb: CallbackQuery, state: FSMContext) -> None:
    gid = cb.data.split(":")[2]
    data = await state.get_data()
    groups: list[dict] = data["groups"]
    selected: list[str] = data.get("selected", [])

    if gid in selected:
        selected.remove(gid)
    else:
        selected.append(gid)

    await state.update_data(selected=selected)

    await cb.message.edit_text(
        _groups_header(len(groups), len(selected)),
        reply_markup=groups_keyboard(groups, selected),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(AnnounceFSM.select_groups, F.data == "grp:all")
async def select_all_groups(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    groups: list[dict] = data["groups"]
    selected = [str(g["id"]) for g in groups]
    await state.update_data(selected=selected)

    await cb.message.edit_text(
        _groups_header(len(groups), len(selected)),
        reply_markup=groups_keyboard(groups, selected),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(AnnounceFSM.select_groups, F.data == "grp:back")
async def back_from_groups(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ Bekor qilindi.")
    await cb.message.answer("Asosiy menyu:", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(AnnounceFSM.select_groups, F.data == "grp:confirm")
async def confirm_groups(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected: list[str] = data.get("selected", [])
    if not selected:
        await cb.answer("⚠️ Hech bo'lmaganda bitta guruh tanlang!", show_alert=True)
        return

    msg_type_label = "rasm + matn" if data["msg_type"] == "photo" else "matn"

    await cb.message.edit_text(
        f"📩 <b>Xabar qabul qilindi</b>\n"
        f"{'🖼' if data['msg_type'] == 'photo' else '📝'} {msg_type_label.capitalize()} ✓\n\n"
        f"✅ Guruhlar tanlandi ({len(selected)} ta)\n\n"
        "Endi xabar yuborish oralig'ini tanlang:",
        reply_markup=interval_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AnnounceFSM.select_interval)
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Interval selection
# ──────────────────────────────────────────────────────────────

@router.callback_query(AnnounceFSM.select_interval, F.data == "int:back")
async def back_from_interval(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    groups = data["groups"]
    selected = data.get("selected", [])
    await state.set_state(AnnounceFSM.select_groups)
    await cb.message.edit_text(
        _groups_header(len(groups), len(selected)),
        reply_markup=groups_keyboard(groups, selected),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(AnnounceFSM.select_interval, F.data.startswith("int:"))
async def pick_interval(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    minutes = int(cb.data.split(":")[1])
    data = await state.get_data()

    user = await session.scalar(select(User).where(User.telegram_id == cb.from_user.id))
    account = await session.scalar(
        select(TelegramAccount).where(
            TelegramAccount.user_id == user.id,
            TelegramAccount.is_active == True,
        )
    )

    msg_type = MessageType.photo if data["msg_type"] == "photo" else MessageType.text
    now = datetime.utcnow()

    ann = Announcement(
        user_id=user.id,
        account_id=account.id,
        message_type=msg_type,
        text=data["text"],
        photo_file_id=data.get("photo_file_id"),
        interval_minutes=minutes,
        is_active=True,
        status=AnnouncementStatus.scheduled,
        next_send_at=now,  # send immediately
        created_at=now,
    )
    session.add(ann)
    await session.flush()

    # Link target groups
    selected_ids = [int(gid) for gid in data["selected"]]
    for gid in selected_ids:
        session.add(AnnouncementGroup(announcement_id=ann.id, group_id=gid))

    await session.commit()

    msg_type_label = "rasm + matn" if data["msg_type"] == "photo" else "matn"
    interval_text = interval_label(minutes)

    await cb.message.edit_text(
        f"✅ <b>Xabar muvaffaqiyatli rejalashtirildi!</b>\n\n"
        f"📄 Xabar: {msg_type_label}\n"
        f"⏰ Oraliq: har {interval_text}\n"
        f"👥 Tanlangan guruhlar: {len(selected_ids)} ta\n"
        f"📱 Akkount: +{account.phone}\n\n"
        "💡 Xabar darhol yuboriladi va keyin tanlangan oraliqda takrorlanadi.",
        parse_mode="HTML",
    )
    await cb.message.answer("Asosiy menyu:", reply_markup=main_menu())
    await state.clear()
    await cb.answer()


# ──────────────────────────────────────────────────────────────
# Edit text sub-flow (triggered from "Mening xabarlari")
# ──────────────────────────────────────────────────────────────

@router.message(AnnounceFSM.edit_text, F.text == CANCEL)
async def cancel_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu())


@router.message(AnnounceFSM.edit_text, F.photo)
async def edit_with_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.caption or not message.caption.strip():
        await message.answer("⚠️ Captionsiz rasmlar qabul qilinmaydi. Qayta yuboring.")
        return

    data = await state.get_data()
    ann_id: int = data["edit_ann_id"]
    ann = await session.get(Announcement, ann_id)
    if ann:
        ann.message_type = MessageType.photo
        ann.text = message.caption.strip()
        ann.photo_file_id = message.photo[-1].file_id
        await session.commit()

    await state.clear()
    await message.answer("✅ Xabar matni yangilandi!", reply_markup=main_menu())


@router.message(AnnounceFSM.edit_text, F.text)
async def edit_with_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    ann_id: int = data["edit_ann_id"]
    ann = await session.get(Announcement, ann_id)
    if ann:
        ann.message_type = MessageType.text
        ann.text = message.text.strip()
        ann.photo_file_id = None
        await session.commit()

    await state.clear()
    await message.answer("✅ Xabar matni yangilandi!", reply_markup=main_menu())

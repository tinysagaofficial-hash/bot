"""
Background scheduler — runs every SCHEDULER_INTERVAL seconds.
Finds due announcements and runs them ALL IN PARALLEL (each in own task+session).
next_send_at is always based on the intended send time, not completion time.
"""

import asyncio
import io
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import SCHEDULER_INTERVAL, SEND_DELAY
from database.models import (
    Announcement, AnnouncementGroup, AnnouncementSend,
    AnnouncementStatus, MessageType, TelegramAccount, Group, User,
)
from userbot import manager

logger = logging.getLogger(__name__)


async def _send_one(ann_id: int, scheduled_time: datetime, session_factory: async_sessionmaker, bot: Bot) -> None:
    """Each announcement runs in its own DB session and asyncio task."""
    async with session_factory() as session:
        ann = await session.get(Announcement, ann_id)
        if not ann or not ann.is_active or ann.status != AnnouncementStatus.scheduled:
            return

        # Auto-stop if subscription expired
        user = await session.get(User, ann.user_id)
        if user:
            now = datetime.utcnow()
            if not user.is_premium and (not user.trial_expires_at or user.trial_expires_at <= now):
                ann.is_active = False
                ann.status = AnnouncementStatus.stopped
                await session.commit()
                logger.info("Auto-stopped ann %s: subscription expired", ann.id)
                return

        if not user or not user.is_active:
            return

        account = await session.get(TelegramAccount, ann.account_id)
        if not account or not account.session_string:
            logger.warning("No account for announcement %s", ann.id)
            return

        try:
            client = await manager.get_client(account.id, account.session_string)
        except Exception as e:
            logger.error("Client error for ann %s: %s", ann.id, e)
            # Mark account as inactive and notify user to re-add
            account.is_active = False
            account.session_string = None
            ann.is_active = False
            ann.status = AnnouncementStatus.stopped
            await session.commit()
            try:
                await bot.send_message(
                    user.telegram_id,
                    "⚠️ <b>Akkaunt sessiyasi tugagan!</b>\n\n"
                    f"📱 +{account.phone} akkauntingiz bilan bog'lanib bo'lmadi.\n\n"
                    "Iltimos, '➕ Akkaunt qo'shish' tugmasini bosib akkauntingizni qayta ulang. "
                    "Shundan so'ng e'lonlaringiz yana ishlaydi.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

        # Download photo once if needed
        photo_bytes = None
        if ann.message_type == MessageType.photo and ann.photo_file_id:
            try:
                file = await bot.get_file(ann.photo_file_id)
                photo_bytes = io.BytesIO()
                await bot.download_file(file.file_path, photo_bytes)
            except Exception as e:
                logger.warning("Photo download failed for ann %s: %s", ann.id, e)

        links = list(await session.scalars(
            select(AnnouncementGroup).where(AnnouncementGroup.announcement_id == ann.id)
        ))

        try:
            for link in links:
                group = await session.get(Group, link.group_id)
                if not group:
                    continue
                try:
                    if photo_bytes:
                        photo_bytes.seek(0)
                    msg_id = await manager.send_to_group(
                        client, group.chat_id, ann.text,
                        photo=io.BytesIO(photo_bytes.getvalue()) if photo_bytes else None,
                    )
                    session.add(AnnouncementSend(
                        announcement_id=ann.id,
                        group_id=group.id,
                        message_id=msg_id,
                        status="sent",
                        sent_at=datetime.utcnow(),
                    ))
                    logger.info("Sent ann %s → group %s (msg %s)", ann.id, group.chat_id, msg_id)
                except Exception as e:
                    session.add(AnnouncementSend(
                        announcement_id=ann.id,
                        group_id=group.id,
                        status="failed",
                        error=str(e)[:200],
                    ))
                    logger.warning("Failed ann %s → group %s: %s", ann.id, group.chat_id, e)

                await asyncio.sleep(SEND_DELAY + random.uniform(0, 2))
        finally:
            await manager.disconnect_client(account.id)

        ann.last_sent_at = datetime.utcnow()
        # next_send_at was already advanced by run_scheduler before this task started
        await session.commit()
        logger.info("Ann %s sent, next send at %s", ann.id, ann.next_send_at)


async def run_scheduler(session_factory: async_sessionmaker, bot: Bot) -> None:
    logger.info("Scheduler started (interval=%ds)", SCHEDULER_INTERVAL)
    while True:
        await asyncio.sleep(SCHEDULER_INTERVAL)
        try:
            due_list = []
            async with session_factory() as session:
                now = datetime.utcnow()
                due = list(await session.scalars(
                    select(Announcement).where(
                        Announcement.is_active == True,
                        Announcement.status == AnnouncementStatus.scheduled,
                        Announcement.next_send_at <= now,
                    )
                ))
                for ann in due:
                    scheduled_time = ann.next_send_at
                    # Advance next_send_at NOW before spawning tasks.
                    # Without this, if _send_one takes longer than SCHEDULER_INTERVAL
                    # the next tick re-picks the same announcement → double send.
                    next_send = scheduled_time + timedelta(minutes=ann.interval_minutes)
                    while next_send <= now:  # skip missed intervals if bot was offline
                        next_send += timedelta(minutes=ann.interval_minutes)
                    ann.next_send_at = next_send
                    due_list.append((ann.id, scheduled_time))
                if due_list:
                    await session.commit()

            if not due_list:
                continue

            logger.info("Scheduler: %d announcement(s) due — running in parallel", len(due_list))

            tasks = [
                asyncio.create_task(
                    _send_one(ann_id, scheduled_time, session_factory, bot)
                )
                for ann_id, scheduled_time in due_list
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (ann_id, _), result in zip(due_list, results):
                if isinstance(result, Exception):
                    logger.error("Task error for ann %s: %s", ann_id, result)

        except Exception as e:
            logger.error("Scheduler loop error: %s", e)

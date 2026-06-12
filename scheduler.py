"""
Background scheduler — runs every SCHEDULER_INTERVAL seconds.
Finds due announcements (is_active=True, next_send_at <= now) and sends them.
"""

import asyncio
import io
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from config import SCHEDULER_INTERVAL, SEND_DELAY
from database.models import (
    Announcement, AnnouncementGroup, AnnouncementSend,
    AnnouncementStatus, MessageType, TelegramAccount, Group, User,
)
from userbot import manager

logger = logging.getLogger(__name__)


async def _send_one(ann: Announcement, session: AsyncSession, bot: Bot) -> None:
    # Auto-stop if user's subscription expired
    user = await session.get(User, ann.user_id)
    if user:
        now = datetime.utcnow()
        if not user.is_premium and (not user.trial_expires_at or user.trial_expires_at <= now):
            ann.is_active = False
            ann.status = AnnouncementStatus.stopped
            await session.commit()
            logger.info("Auto-stopped ann %s: user %s subscription expired", ann.id, ann.user_id)
            return

    account = await session.get(TelegramAccount, ann.account_id)
    if not account or not account.session_string:
        logger.warning("No account for announcement %s", ann.id)
        return

    try:
        client = await manager.get_client(account.id, account.session_string)
    except Exception as e:
        logger.error("Client error for announcement %s: %s", ann.id, e)
        return

    # Download photo once if needed
    photo_bytes = None  # io.BytesIO or None
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
                logger.info("Sent ann %s to group %s (msg %s)", ann.id, group.chat_id, msg_id)
            except Exception as e:
                session.add(AnnouncementSend(
                    announcement_id=ann.id,
                    group_id=group.id,
                    status="failed",
                    error=str(e)[:200],
                ))
                logger.warning("Failed ann %s → group %s: %s", ann.id, group.chat_id, e)

            await asyncio.sleep(SEND_DELAY)
    finally:
        # Always disconnect after send cycle — frees RAM (critical for 1k+ users)
        await manager.disconnect_client(account.id)

    # Schedule next run
    now = datetime.utcnow()
    ann.last_sent_at = now
    ann.next_send_at = now + timedelta(minutes=ann.interval_minutes)
    await session.commit()


async def run_scheduler(session_factory: async_sessionmaker, bot: Bot) -> None:
    logger.info("Scheduler started (interval=%ds)", SCHEDULER_INTERVAL)
    while True:
        await asyncio.sleep(SCHEDULER_INTERVAL)
        try:
            async with session_factory() as session:
                now = datetime.utcnow()
                due = list(await session.scalars(
                    select(Announcement).where(
                        Announcement.is_active == True,
                        Announcement.status == AnnouncementStatus.scheduled,
                        Announcement.next_send_at <= now,
                    )
                ))

                if due:
                    logger.info("Scheduler: %d announcement(s) due", len(due))

                for ann in due:
                    try:
                        await _send_one(ann, session, bot)
                    except Exception as e:
                        logger.error("Scheduler error for ann %s: %s", ann.id, e)

        except Exception as e:
            logger.error("Scheduler loop error: %s", e)

"""
Manages Telethon (MTProto) user-account clients.

Each TelegramAccount row gets one persistent TelegramClient stored in _clients.
Clients are created lazily and re-used across requests.
"""

import asyncio
import io
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, ChatForbidden, ChannelForbidden

from config import API_ID, API_HASH

logger = logging.getLogger(__name__)

# account_id → TelegramClient
_clients: dict[int, TelegramClient] = {}

# Temporary login clients keyed by bot user_id (cleared after login)
_login_sessions: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# Persistent client management
# ---------------------------------------------------------------------------

async def get_client(account_id: int, session_string: str) -> TelegramClient:
    client = _clients.get(account_id)
    if client and client.is_connected():
        return client

    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        raise RuntimeError("Session expired. Please re-add the account.")

    _clients[account_id] = client
    return client


async def disconnect_client(account_id: int) -> None:
    client = _clients.pop(account_id, None)
    if client:
        await client.disconnect()


# ---------------------------------------------------------------------------
# Login flow (temporary clients)
# ---------------------------------------------------------------------------

async def start_login(bot_user_id: int, phone: str) -> str:
    """
    Sends OTP to *phone* and stores a temporary client.
    Returns phone_code_hash.
    """
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()

    result = await client.send_code_request(phone)

    _login_sessions[bot_user_id] = {
        "client": client,
        "phone": phone,
        "phone_code_hash": result.phone_code_hash,
    }
    return result.phone_code_hash


def has_login_session(bot_user_id: int) -> bool:
    return bot_user_id in _login_sessions


async def finish_login(bot_user_id: int, code: str) -> tuple[str, str]:
    """
    Verifies OTP code.  Returns (session_string, phone).
    Raises SessionPasswordNeededError if 2FA is enabled.
    """
    data = _login_sessions[bot_user_id]
    client: TelegramClient = data["client"]
    phone: str = data["phone"]
    phone_code_hash: str = data["phone_code_hash"]

    await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    session_string = client.session.save()
    del _login_sessions[bot_user_id]
    return session_string, phone


async def finish_login_2fa(bot_user_id: int, password: str) -> tuple[str, str]:
    """Completes 2FA login.  Returns (session_string, phone)."""
    data = _login_sessions[bot_user_id]
    client: TelegramClient = data["client"]
    phone: str = data["phone"]

    await client.sign_in(password=password)
    session_string = client.session.save()
    del _login_sessions[bot_user_id]
    return session_string, phone


async def cancel_login(bot_user_id: int) -> None:
    data = _login_sessions.pop(bot_user_id, None)
    if data:
        try:
            await data["client"].disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Group discovery
# ---------------------------------------------------------------------------

async def fetch_groups(client: TelegramClient) -> list[dict]:
    """Returns all groups/supergroups the account is a member of."""
    groups = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (ChatForbidden, ChannelForbidden)):
            continue

        is_broadcast = getattr(entity, "broadcast", False)
        is_megagroup = getattr(entity, "megagroup", False)
        is_chat = isinstance(entity, Chat)

        # Include regular groups and supergroups; skip channels (broadcast)
        if is_chat or is_megagroup or (isinstance(entity, Channel) and not is_broadcast):
            groups.append(
                {
                    "chat_id": dialog.id,
                    "title": dialog.title or "—",
                    "username": getattr(entity, "username", None),
                    "member_count": getattr(entity, "participants_count", 0) or 0,
                }
            )
    return groups


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

async def send_to_group(
    client: TelegramClient,
    chat_id: int,
    text: str,
    photo: Optional[io.BytesIO] = None,
) -> int:
    """
    Sends a message (optionally with photo) to a group.
    Returns the sent message ID.
    Handles FloodWait by sleeping then re-raising.
    """
    try:
        if photo:
            photo.seek(0)
            photo.name = "photo.jpg"  # tells Telegram to treat it as photo not file
            msg = await client.send_file(
                chat_id,
                photo,
                caption=text[:1024],
                parse_mode="html",
                force_document=False,
            )
            # If text was truncated, send the rest as a separate message
            if len(text) > 1024:
                await client.send_message(chat_id, text[1024:], parse_mode="html")
        else:
            msg = await client.send_message(chat_id, text, parse_mode="html")
        return msg.id

    except FloodWaitError as e:
        logger.warning("FloodWait %ds on chat %s", e.seconds, chat_id)
        await asyncio.sleep(e.seconds + 1)
        raise

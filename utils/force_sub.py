"""
utils/force_sub.py - Force-subscribe logic.

At startup `load_channels()` resolves every channel in FORCE_SUB_CHANNELS to
{id, title, link}. `get_unjoined()` then checks a user's membership and
`build_markup()` creates the Join / Try Again buttons.

Misconfigured channels (bot not admin, bad ID) are logged and skipped so that
users are never locked out by an admin mistake.
"""
import asyncio
import logging
from typing import Dict, List

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait, RPCError, UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config

log = logging.getLogger(__name__)

channels: List[Dict] = []


async def load_channels(client: Client) -> None:
    channels.clear()
    for ref in config.FORCE_SUB_CHANNELS:
        try:
            chat = await client.get_chat(ref)
            if chat.username:
                link = f"https://t.me/{chat.username}"
            else:
                link = chat.invite_link or await client.export_chat_invite_link(chat.id)
            channels.append({"id": chat.id, "title": chat.title, "link": link})
            log.info("Force-sub channel loaded: %s (%s)", chat.title, chat.id)
        except RPCError as exc:
            log.error(
                "Force-sub channel %r skipped: %s (add the bot as admin of that channel)", ref, exc
            )


async def get_unjoined(client: Client, user_id: int) -> List[Dict]:
    """Return the list of required channels the user has NOT joined."""
    missing = []
    for ch in channels:
        for attempt in (1, 2):
            try:
                member = await client.get_chat_member(ch["id"], user_id)
                not_member = member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) or (
                    member.status == ChatMemberStatus.RESTRICTED and not getattr(member, "is_member", True)
                )
                if not_member:
                    missing.append(ch)
                break
            except UserNotParticipant:
                missing.append(ch)
                break
            except FloodWait as exc:
                if attempt == 2:
                    break
                await asyncio.sleep(int(getattr(exc, "value", 3)) + 1)
            except RPCError as exc:
                log.error("Membership check failed for channel %s: %s", ch["id"], exc)
                break  # fail open: don't lock users out because of a config error
    return missing


def build_markup(unjoined: List[Dict], token: str = "") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"📢 Join {ch['title']}", url=ch["link"])] for ch in unjoined]
    rows.append([InlineKeyboardButton("🔄 Try Again", callback_data=f"retry:{token}")])
    return InlineKeyboardMarkup(rows)

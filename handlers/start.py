"""
handlers/start.py - User-facing logic.

  * guard (group -1): registers users, enforces bans and anti-flood BEFORE any other handler
  * /start               -> welcome message
  * /start <token>       -> force-sub check, then deliver the file(s)
  * "Try Again" callback -> re-check membership and deliver
"""
import html
import logging
import re

from pyrogram import Client, filters
from pyrogram.errors import RPCError

import config
from database import mongo as db
from utils import force_sub
from utils.helpers import ADMIN_HELP, admin_only, deliver_content, limiter, safe_call

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


# ------------------------------------------------------------------ guard --
@Client.on_message(filters.private, group=-1)
async def guard_message(client: Client, message):
    """Runs first for every private message: register, ban check, flood check."""
    user = message.from_user
    if not user:
        return
    await db.add_user(user.id, user.first_name, user.username)

    if user.id in config.ADMINS:
        return  # admins are exempt

    if db.is_banned(user.id):
        await safe_call(message.reply_text, "🚫 You are banned from using this bot.")
        message.stop_propagation()

    verdict = limiter.check(user.id)
    if verdict == "just_blocked":
        await safe_call(
            message.reply_text,
            f"⏳ Slow down! You're blocked for {config.FLOOD_BLOCK_SECONDS} seconds.",
        )
        message.stop_propagation()
    elif verdict == "blocked":
        message.stop_propagation()  # silently ignore while blocked


@Client.on_callback_query(group=-1)
async def guard_callback(client: Client, cq):
    user = cq.from_user
    if user.id in config.ADMINS:
        return
    if db.is_banned(user.id):
        await cq.answer("🚫 You are banned.", show_alert=True)
        cq.stop_propagation()
    if limiter.check(user.id) != "ok":
        await cq.answer("⏳ Too fast, please wait a moment.", show_alert=True)
        cq.stop_propagation()


# ------------------------------------------------------------------ /start --
def _welcome(name: str) -> str:
    return (
        f"👋 Hello <b>{html.escape(name)}</b>!\n\n"
        "I deliver files shared through special links. "
        "Open a link someone sent you and I'll do the rest."
    )


@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message):
    user = message.from_user
    payload = message.command[1] if len(message.command) > 1 else None

    if not payload:
        text = ADMIN_HELP if user.id in config.ADMINS else _welcome(user.first_name or "there")
        await message.reply_text(text)
        return

    if not TOKEN_RE.match(payload):
        await message.reply_text("❌ This link is invalid.")
        return

    # Force-subscribe check (admins bypass)
    if user.id not in config.ADMINS:
        unjoined = await force_sub.get_unjoined(client, user.id)
        if unjoined:
            await message.reply_text(
                "🔒 <b>Access locked</b>\n\nPlease join the channel(s) below, "
                "then press <b>Try Again</b>.",
                reply_markup=force_sub.build_markup(unjoined, payload),
            )
            return

    await deliver_content(client, message.chat.id, payload)


@Client.on_callback_query(filters.regex(r"^retry:(.*)$"))
async def retry_callback(client: Client, cq):
    token = cq.matches[0].group(1)
    unjoined = await force_sub.get_unjoined(client, cq.from_user.id)
    if unjoined:
        await cq.answer("❌ You haven't joined all required channels yet.", show_alert=True)
        return

    await cq.answer("✅ Thanks! Sending...")
    chat_id = cq.message.chat.id
    try:
        await cq.message.delete()
    except RPCError:
        pass

    if token and TOKEN_RE.match(token):
        await deliver_content(client, chat_id, token)
    else:
        await safe_call(client.send_message, chat_id, _welcome(cq.from_user.first_name or "there"))


# ------------------------------------------------- anything else (non-admins) --
@Client.on_message(filters.private & ~admin_only & ~filters.command("start"))
async def fallback(client: Client, message):
    await message.reply_text("ℹ️ Please open a file link shared with you to get your files.")

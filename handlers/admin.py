"""
handlers/admin.py - Admin-only commands and single-file uploads.

  Send a file to the bot -> stored in DB channel -> shareable link returned
  /stats  /users  /ban <id> [reason]  /unban <id>
  (all of them are also reachable from the Help buttons, see handlers/panel.py)
"""
import html
import logging

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database import mongo as db
from utils.helpers import (
    admin_only, ask_filter, batch_filter, build_link, human_size, make_token,
    media_filter, media_info, safe_call, send_users_report, stats_text,
)

log = logging.getLogger(__name__)


# ----------------------------------------------------------- single upload --
@Client.on_message(filters.private & admin_only & media_filter & ~batch_filter & ~ask_filter)
async def upload_single(client: Client, message):
    """Copy the admin's file into the DB channel and return a deep link."""
    try:
        stored = await safe_call(message.copy, config.DB_CHANNEL_ID)
    except RPCError as exc:
        log.exception("Failed to store file in DB channel")
        await message.reply_text(f"❌ Could not store the file in the DB channel:\n<code>{html.escape(str(exc))}</code>")
        return

    kind, name, size = media_info(message)
    token = make_token()
    await db.create_file(token, stored.id, kind, name, size, message.from_user.id)

    link = build_link(client, token)
    await message.reply_text(
        f"✅ <b>File stored</b>\n"
        f"📄 <code>{html.escape(name)}</code> ({human_size(size)})\n\n"
        f"🔗 <code>{link}</code>",
        quote=True,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("📤 Share link", url=f"https://t.me/share/url?url={link}")]]
        ),
    )


# ------------------------------------------------------------------- stats --
@Client.on_message(filters.command("stats") & filters.private & admin_only)
async def stats_cmd(client: Client, message):
    await message.reply_text(await stats_text())


# ------------------------------------------------------------------- users --
@Client.on_message(filters.command("users") & filters.private & admin_only)
async def users_cmd(client: Client, message):
    await send_users_report(client, message.chat.id)


# --------------------------------------------------------------- ban/unban --
def _target_id(message):
    if len(message.command) > 1 and message.command[1].lstrip("-").isdigit():
        return int(message.command[1])
    return None


@Client.on_message(filters.command("ban") & filters.private & admin_only)
async def ban_cmd(client: Client, message):
    uid = _target_id(message)
    if uid is None:
        await message.reply_text("Usage: <code>/ban &lt;user_id&gt; [reason]</code>")
        return
    if uid in config.ADMINS:
        await message.reply_text("❌ You can't ban an admin.")
        return
    reason = " ".join(message.command[2:])
    await db.ban_user(uid, reason)
    await message.reply_text(f"🚫 User <code>{uid}</code> banned.")


@Client.on_message(filters.command("unban") & filters.private & admin_only)
async def unban_cmd(client: Client, message):
    uid = _target_id(message)
    if uid is None:
        await message.reply_text("Usage: <code>/unban &lt;user_id&gt;</code>")
        return
    found = await db.unban_user(uid)
    await message.reply_text(
        f"✅ User <code>{uid}</code> unbanned." if found else "⚠️ That user isn't in the database."
    )

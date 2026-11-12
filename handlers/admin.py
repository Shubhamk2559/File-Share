"""
handlers/admin.py - Admin-only commands and single-file uploads.

  Send a file to the bot -> stored in DB channel -> shareable link returned
  /stats  /users  /ban <id> [reason]  /unban <id>  /help
"""
import html
import io
import logging
import time

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database import mongo as db
from utils.helpers import (
    ADMIN_HELP, START_TIME, admin_only, batch_filter, build_link, human_size,
    humanize, make_token, media_filter, media_info, safe_call,
)

log = logging.getLogger(__name__)


@Client.on_message(filters.command("help") & filters.private & admin_only)
async def admin_help(client: Client, message):
    await message.reply_text(ADMIN_HELP)


# ----------------------------------------------------------- single upload --
@Client.on_message(filters.private & admin_only & media_filter & ~batch_filter)
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
    s = await db.get_stats()
    delete_txt = humanize(config.AUTO_DELETE_SECONDS) if config.AUTO_DELETE_SECONDS else "off"
    await message.reply_text(
        "📊 <b>Bot statistics</b>\n\n"
        f"👥 Users: <b>{s['users']}</b>\n"
        f"🚫 Banned: <b>{s['banned']}</b>\n"
        f"📁 Files: <b>{s['files']}</b>\n"
        f"📦 Batches: <b>{s['batches']}</b>\n"
        f"⬇️ Deliveries: <b>{s['downloads']}</b>\n"
        f"🗑 Pending deletions: <b>{s['pending_deletions']}</b>\n\n"
        f"⏱ Auto-delete: <b>{delete_txt}</b>\n"
        f"🔐 Protect content: <b>{'on' if config.PROTECT_CONTENT else 'off'}</b>\n"
        f"🕒 Uptime: <b>{humanize(time.time() - START_TIME)}</b>"
    )


# ------------------------------------------------------------------- users --
@Client.on_message(filters.command("users") & filters.private & admin_only)
async def users_cmd(client: Client, message):
    total, banned = await db.count_users(), await db.count_banned()
    lines = []
    async for u in db.iter_users():
        lines.append(
            f"{u['user_id']} | @{u.get('username') or '-'} | "
            f"{u.get('first_name') or '-'} | {'BANNED' if u.get('banned') else 'ok'}"
        )
    await message.reply_text(f"👥 Total: <b>{total}</b> | 🚫 Banned: <b>{banned}</b>")
    if lines:
        bio = io.BytesIO("\n".join(lines).encode("utf-8"))
        bio.name = "users.txt"
        await message.reply_document(bio, caption="Full user list")


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

"""
handlers/batch.py - Multi-file links.

  /batch            start collecting files
  (send files)      each file is stored in the DB channel
  /done             create ONE link for everything collected
  /cancel           abort the session
"""
import logging

from pyrogram import Client, filters
from pyrogram.errors import RPCError

import config
from database import mongo as db
from utils.helpers import (
    admin_only, batch_filter, batch_sessions, build_link, make_token,
    media_filter, safe_call,
)

log = logging.getLogger(__name__)


@Client.on_message(filters.command("batch") & filters.private & admin_only)
async def batch_start(client: Client, message):
    batch_sessions[message.from_user.id] = []
    await message.reply_text(
        "📦 <b>Batch mode on.</b>\n\n"
        f"Send me up to {config.MAX_BATCH_SIZE} files. When finished send /done "
        "(or /cancel to abort)."
    )


@Client.on_message(filters.private & admin_only & media_filter & batch_filter)
async def batch_add(client: Client, message):
    uid = message.from_user.id
    items = batch_sessions[uid]
    if len(items) >= config.MAX_BATCH_SIZE:
        await message.reply_text("⚠️ Batch limit reached. Send /done to get your link.")
        return
    try:
        stored = await safe_call(message.copy, config.DB_CHANNEL_ID)
    except RPCError as exc:
        log.exception("Batch: failed to store file")
        await message.reply_text(f"❌ Failed to store this file: <code>{exc}</code>")
        return
    items.append(stored.id)
    await message.reply_text(f"➕ Added (<b>{len(items)}</b> so far)", quote=True)


@Client.on_message(filters.command(["done", "link", "finish"]) & filters.private & admin_only & batch_filter)
async def batch_done(client: Client, message):
    uid = message.from_user.id
    ids = batch_sessions.pop(uid, [])
    if not ids:
        await message.reply_text("⚠️ Batch was empty, nothing created.")
        return
    token = make_token()
    await db.create_batch(token, ids, uid)
    await message.reply_text(
        f"✅ <b>Batch created</b> ({len(ids)} files)\n\n🔗 <code>{build_link(client, token)}</code>",
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command("cancel") & filters.private & admin_only & batch_filter)
async def batch_cancel(client: Client, message):
    batch_sessions.pop(message.from_user.id, None)
    await message.reply_text("❎ Batch cancelled. (Files already copied stay in the DB channel.)")

"""
handlers/batch.py - Multi-file links.

Button flow: Help -> Batch (see handlers/panel.py), send files, press Done.
Commands still work: /batch, /done, /cancel.
"""
import logging

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from database import mongo as db
from utils import ui
from utils.helpers import (
    admin_cb, admin_only, ask_sessions, batch_filter, batch_sessions, build_link,
    make_token, media_filter, safe_call,
)

log = logging.getLogger(__name__)


async def _finish(client: Client, uid: int):
    """Create the batch link. Returns (text, markup) or None if the batch is empty."""
    ids = batch_sessions.pop(uid, [])
    if not ids:
        return None
    token = make_token()
    await db.create_batch(token, ids, uid)
    link = build_link(client, token)
    text = f"✅ <b>Batch created</b> ({len(ids)} files)\n\n🔗 <code>{link}</code>"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share link", url=f"https://t.me/share/url?url={link}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="menu:help")],
    ])
    return text, markup


@Client.on_message(filters.command("batch") & filters.private & admin_only)
async def batch_start(client: Client, message):
    ask_sessions.pop(message.from_user.id, None)
    batch_sessions[message.from_user.id] = []
    await message.reply_text(
        "📦 <b>Batch mode on.</b>\n\n"
        f"Send me up to {config.MAX_BATCH_SIZE} files, then press <b>Done</b>.",
        reply_markup=ui.batch_markup(),
    )


@Client.on_message(filters.private & admin_only & media_filter & batch_filter)
async def batch_add(client: Client, message):
    uid = message.from_user.id
    items = batch_sessions[uid]
    if len(items) >= config.MAX_BATCH_SIZE:
        await message.reply_text("⚠️ Batch limit reached. Press Done to get your link.", reply_markup=ui.batch_markup())
        return
    try:
        stored = await safe_call(message.copy, config.DB_CHANNEL_ID)
    except RPCError as exc:
        log.exception("Batch: failed to store file")
        await message.reply_text(f"❌ Failed to store this file: <code>{exc}</code>")
        return
    items.append(stored.id)
    await message.reply_text(f"➕ Added (<b>{len(items)}</b> so far)", quote=True, reply_markup=ui.batch_markup())


@Client.on_message(filters.command(["done", "link", "finish"]) & filters.private & admin_only & batch_filter)
async def batch_done(client: Client, message):
    result = await _finish(client, message.from_user.id)
    if not result:
        await message.reply_text("⚠️ Batch was empty, nothing created.")
        return
    text, markup = result
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_message(filters.command("cancel") & filters.private & admin_only & batch_filter)
async def batch_cancel(client: Client, message):
    batch_sessions.pop(message.from_user.id, None)
    await message.reply_text(
        "❎ Batch cancelled. (Files already copied stay in the DB channel.)",
        reply_markup=ui.back_markup("help"),
    )


# ---------------------------------------------------------------- buttons --
@Client.on_callback_query(filters.regex(r"^bt:(done|cancel)$") & admin_cb)
async def batch_buttons(client: Client, cq):
    uid = cq.from_user.id
    action = cq.matches[0].group(1)

    if uid not in batch_sessions:
        await cq.answer("No active batch. Start one from Help → Batch.", show_alert=True)
        return

    if action == "cancel":
        batch_sessions.pop(uid, None)
        text, markup = "❎ Batch cancelled. (Files already copied stay in the DB channel.)", ui.back_markup("help")
    else:
        result = await _finish(client, uid)
        if not result:
            await cq.answer("Send at least one file first.", show_alert=True)
            return
        text, markup = result

    try:
        await cq.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except RPCError:
        await safe_call(client.send_message, cq.message.chat.id, text, reply_markup=markup)
    await cq.answer()

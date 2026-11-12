"""
handlers/panel.py - Button-driven menus. Every admin command is reachable by a button.

  /help, /id                 -> for everyone
  menu:*   Home / Help / About / Settings pages (edit the same message)
  adm:*    admin actions (stats, users, batch, broadcast, ban, unban)
  ask:*    cancel a pending "send me the ID / message" prompt
  bc:*     confirm / cancel a broadcast
  usr:id   show the user's Telegram ID
"""
import logging

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified, RPCError

import config
from database import mongo as db
from handlers import broadcast
from utils import ui
from utils.helpers import (
    admin_cb, admin_only, ask_filter, ask_sessions, batch_sessions,
    not_command, send_users_report, stats_text,
)

log = logging.getLogger(__name__)


async def _edit(cq, text: str, markup) -> None:
    try:
        await cq.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except RPCError as exc:
        log.warning("Menu edit failed: %s", exc)


# --------------------------------------------------------- plain commands --
@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message):
    is_admin = message.from_user.id in config.ADMINS
    await message.reply_text(ui.help_text(is_admin), reply_markup=ui.help_markup(is_admin))


@Client.on_message(filters.command("id") & filters.private)
async def id_cmd(client: Client, message):
    await message.reply_text(f"🆔 Your ID: <code>{message.from_user.id}</code>", quote=True)


# ------------------------------------------------------------------ pages --
@Client.on_callback_query(filters.regex(r"^menu:(home|help|about|settings)$"))
async def menu_cb(client: Client, cq):
    page = cq.matches[0].group(1)
    user = cq.from_user
    is_admin = user.id in config.ADMINS
    ask_sessions.pop(user.id, None)  # leaving a prompt cancels it

    if page == "home":
        text, markup = ui.welcome_text(user, client.me), ui.home_markup(is_admin)
    elif page == "help":
        text, markup = ui.help_text(is_admin), ui.help_markup(is_admin)
    elif page == "about":
        text, markup = ui.about_text(client.me), ui.back_markup("home")
    else:  # settings
        if not is_admin:
            await cq.answer("Admins only.", show_alert=True)
            return
        text, markup = ui.settings_text(), ui.back_markup("home")

    await _edit(cq, text, markup)
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^usr:id$"))
async def my_id_cb(client: Client, cq):
    await cq.answer(f"Your ID: {cq.from_user.id}", show_alert=True)


# ---------------------------------------------------------- admin actions --
@Client.on_callback_query(filters.regex(r"^adm:(stats|users|batch|broadcast|ban|unban)$") & admin_cb)
async def admin_action_cb(client: Client, cq):
    action = cq.matches[0].group(1)
    uid = cq.from_user.id

    if action == "stats":
        await _edit(cq, await stats_text(), ui.back_markup("help"))
        await cq.answer()
        return

    if action == "users":
        await cq.answer("Preparing user list...")
        await send_users_report(client, cq.message.chat.id)
        return

    # The rest start a multi-step flow: only one flow at a time.
    ask_sessions.pop(uid, None)

    if action == "batch":
        batch_sessions[uid] = []
        await _edit(
            cq,
            "📦 <b>Batch mode on.</b>\n\n"
            f"Send me up to {config.MAX_BATCH_SIZE} files, then press <b>Done</b>.",
            ui.batch_markup(),
        )
    elif action == "broadcast":
        batch_sessions.pop(uid, None)
        ask_sessions[uid] = {"action": "broadcast"}
        await _edit(
            cq,
            "📢 <b>Broadcast</b>\n\nSend (or forward) the message you want to send to all users.",
            ui.cancel_markup(),
        )
    else:  # ban / unban
        batch_sessions.pop(uid, None)
        ask_sessions[uid] = {"action": action}
        extra = " You can add a reason after the ID." if action == "ban" else ""
        await _edit(
            cq,
            f"{'🚫' if action == 'ban' else '✅'} <b>{action.capitalize()} user</b>\n\n"
            f"Send the user's numeric ID.{extra}",
            ui.cancel_markup(),
        )
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^ask:cancel$") & admin_cb)
async def ask_cancel_cb(client: Client, cq):
    ask_sessions.pop(cq.from_user.id, None)
    await _edit(cq, ui.help_text(True), ui.help_markup(True))
    await cq.answer("Cancelled.")


@Client.on_message(filters.command("cancel") & filters.private & admin_only & ask_filter)
async def ask_cancel_cmd(client: Client, message):
    ask_sessions.pop(message.from_user.id, None)
    await message.reply_text("❎ Cancelled.", reply_markup=ui.back_markup("help"))


# ------------------------------------------- replies to ban/unban/broadcast --
@Client.on_message(filters.private & admin_only & ask_filter & not_command)
async def ask_input(client: Client, message):
    uid = message.from_user.id
    session = ask_sessions[uid]
    action = session["action"]

    if action in ("ban", "unban"):
        parts = (message.text or "").split(None, 1)
        if not parts or not parts[0].lstrip("-").isdigit():
            await message.reply_text("⚠️ Please send a numeric user ID.", reply_markup=ui.cancel_markup())
            return
        target = int(parts[0])

        if action == "ban":
            if target in config.ADMINS:
                await message.reply_text("❌ You can't ban an admin.", reply_markup=ui.cancel_markup())
                return
            await db.ban_user(target, parts[1] if len(parts) > 1 else "")
            result = f"🚫 User <code>{target}</code> banned."
        else:
            found = await db.unban_user(target)
            result = (
                f"✅ User <code>{target}</code> unbanned." if found
                else "⚠️ That user isn't in the database."
            )
        ask_sessions.pop(uid, None)
        await message.reply_text(result, reply_markup=ui.back_markup("help"))
        return

    # broadcast: remember the message and ask for confirmation
    session["source"] = message
    await message.reply_text(
        "📢 This message will be sent to <b>all users</b>. Continue?",
        quote=True,
        reply_markup=ui.confirm_broadcast_markup(),
    )


@Client.on_callback_query(filters.regex(r"^bc:(yes|no)$") & admin_cb)
async def broadcast_confirm_cb(client: Client, cq):
    uid = cq.from_user.id
    session = ask_sessions.get(uid)
    if not session or session.get("action") != "broadcast" or "source" not in session:
        await cq.answer("This request expired. Start again from Help.", show_alert=True)
        return

    if cq.matches[0].group(1) == "no":
        ask_sessions.pop(uid, None)
        await _edit(cq, "❎ Broadcast cancelled.", ui.back_markup("help"))
        await cq.answer()
        return

    if broadcast.is_running():
        await cq.answer("A broadcast is already running.", show_alert=True)
        return

    source = session["source"]
    ask_sessions.pop(uid, None)
    try:
        status = await cq.message.edit_text("📢 Starting broadcast...")
    except RPCError:
        status = await client.send_message(cq.message.chat.id, "📢 Starting broadcast...")
    broadcast.launch(source, status)
    await cq.answer()

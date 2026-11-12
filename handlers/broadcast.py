"""
handlers/broadcast.py - /broadcast (reply to any message).

Copies the replied-to message to every non-banned user, throttled to respect
Telegram limits. Dead users (blocked the bot / deactivated) are pruned.
Runs as a background task so the bot stays responsive.
"""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait, InputUserDeactivated, MessageNotModified, PeerIdInvalid,
    RPCError, UserIsBlocked,
)

from database import mongo as db
from utils.helpers import admin_only, safe_call

log = logging.getLogger(__name__)

_lock = asyncio.Lock()
_tasks: set = set()  # keep references so tasks aren't garbage-collected


async def _run_broadcast(source, status_msg) -> None:
    async with _lock:
        total = await db.count_users()
        done = ok = blocked = failed = 0

        async for uid in db.iter_user_ids():
            try:
                await safe_call(source.copy, uid)
                ok += 1
            except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                await db.remove_user(uid)
                blocked += 1
            except FloodWait:
                failed += 1
            except RPCError as exc:
                log.warning("Broadcast to %s failed: %s", uid, exc)
                failed += 1
            except Exception:
                log.exception("Unexpected broadcast error for %s", uid)
                failed += 1

            done += 1
            await asyncio.sleep(0.05)  # ~20 msgs/sec, safely under Telegram's limit

            if done % 50 == 0:
                try:
                    await status_msg.edit_text(f"📢 Broadcasting... {done}/{total}")
                except (MessageNotModified, RPCError):
                    pass

        try:
            await status_msg.edit_text(
                "✅ <b>Broadcast finished</b>\n\n"
                f"Total: {total}\nDelivered: {ok}\n"
                f"Blocked/removed: {blocked}\nFailed: {failed}"
            )
        except RPCError:
            pass


@Client.on_message(filters.command("broadcast") & filters.private & admin_only)
async def broadcast_cmd(client: Client, message):
    source = message.reply_to_message
    if not source:
        await message.reply_text("Reply to the message you want to broadcast with /broadcast")
        return
    if _lock.locked():
        await message.reply_text("⚠️ A broadcast is already running.")
        return

    status = await message.reply_text("📢 Starting broadcast...")
    task = asyncio.create_task(_run_broadcast(source, status))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

"""
utils/scheduler.py - Persistent auto-delete worker.

Delete jobs live in MongoDB (collection `deletions`), so they survive restarts.
Every POLL_INTERVAL seconds the worker claims due jobs, deletes the messages,
and sends a small "files deleted" note with a re-download button.

Note: Telegram only lets bots delete their own private-chat messages that are
less than 48 hours old, so very long downtimes can leave old messages behind.
"""
import asyncio
import logging
import time

from pyrogram import Client
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import mongo as db
from utils.helpers import safe_call

log = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds


async def _process_due(client: Client) -> None:
    while True:
        job = await db.pop_due_deletion(time.time())
        if not job:
            return

        chat_id, ids = job["chat_id"], job["message_ids"]
        for i in range(0, len(ids), 100):
            try:
                await safe_call(client.delete_messages, chat_id, ids[i:i + 100])
            except RPCError as exc:
                log.warning("Auto-delete failed in chat %s: %s", chat_id, exc)

        token = job.get("token")
        if token:
            try:
                await safe_call(
                    client.send_message,
                    chat_id,
                    "🗑 Your files were deleted automatically. Tap below to get them again.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(
                            "🔁 Get files again",
                            url=f"https://t.me/{client.me.username}?start={token}",
                        )]]
                    ),
                )
            except RPCError:
                pass  # user may have blocked the bot


async def run_scheduler(client: Client) -> None:
    log.info("Auto-delete scheduler started (poll every %ss)", POLL_INTERVAL)
    while True:
        try:
            await _process_due(client)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler iteration failed")
        await asyncio.sleep(POLL_INTERVAL)

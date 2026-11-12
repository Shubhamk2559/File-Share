"""
utils/helpers.py - Shared helpers.

  * custom filters (admin_only, media_filter, batch_filter) + batch session store
  * safe_call(): retries on FloodWait
  * RateLimiter: sliding-window anti-flood
  * token / link helpers
  * deliver_content(): copies stored files to a user and schedules auto-delete
"""
import asyncio
import io
import logging
import secrets
import time
from collections import defaultdict, deque
from typing import Dict, List

from pyrogram import filters
from pyrogram.errors import FloodWait, RPCError

import config
from database import mongo as db

log = logging.getLogger(__name__)

START_TIME = time.time()

# ---------------------------------------------------------------- filters --
batch_sessions: Dict[int, List[int]] = {}  # admin_id -> list of DB-channel message IDs
ask_sessions: Dict[int, dict] = {}         # admin_id -> {"action": "ban|unban|broadcast", "source": Message}


async def _is_admin(_, __, message) -> bool:
    return bool(message.from_user and message.from_user.id in config.ADMINS)


async def _in_batch(_, __, message) -> bool:
    return bool(message.from_user and message.from_user.id in batch_sessions)


async def _in_ask(_, __, message) -> bool:
    return bool(message.from_user and message.from_user.id in ask_sessions)


async def _not_command(_, __, message) -> bool:
    return not (message.text or "").startswith("/")


async def _is_admin_cb(_, __, cq) -> bool:
    return bool(cq.from_user and cq.from_user.id in config.ADMINS)


admin_only = filters.create(_is_admin)
admin_cb = filters.create(_is_admin_cb)
batch_filter = filters.create(_in_batch)
ask_filter = filters.create(_in_ask)
not_command = filters.create(_not_command)
media_filter = (
    filters.document | filters.video | filters.audio | filters.photo
    | filters.voice | filters.animation | filters.video_note
)


# ----------------------------------------------------------- misc helpers --
async def safe_call(func, *args, retries: int = 3, **kwargs):
    """Await func(*args, **kwargs); on FloodWait sleep and retry."""
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except FloodWait as exc:
            wait = int(getattr(exc, "value", None) or getattr(exc, "x", 5))
            log.warning("FloodWait %ss in %s (attempt %d/%d)", wait, getattr(func, "__name__", func), attempt, retries)
            if attempt == retries:
                raise
            await asyncio.sleep(wait + 1)


def humanize(seconds: float) -> str:
    seconds = int(seconds)
    parts = []
    for label, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            n, seconds = divmod(seconds, size)
            parts.append(f"{n}{label}")
    return " ".join(parts) or "0s"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def media_info(message):
    """Return (kind, file_name, file_size) for the media in a message."""
    for kind in ("document", "video", "audio", "photo", "voice", "animation", "video_note"):
        media = getattr(message, kind, None)
        if media:
            name = getattr(media, "file_name", None) or kind
            size = getattr(media, "file_size", 0) or 0
            return kind, name, size
    return "unknown", "unknown", 0


def make_token() -> str:
    """12-char base64url token: only A-Z a-z 0-9 _ - (valid for ?start=)."""
    return secrets.token_urlsafe(9)


def build_link(client, token: str) -> str:
    return f"https://t.me/{client.me.username}?start={token}"


# ------------------------------------------------------- admin report text --
async def stats_text() -> str:
    s = await db.get_stats()
    delete_txt = humanize(config.AUTO_DELETE_SECONDS) if config.AUTO_DELETE_SECONDS else "off"
    return (
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


async def send_users_report(client, chat_id: int) -> None:
    total, banned = await db.count_users(), await db.count_banned()
    lines = []
    async for u in db.iter_users():
        lines.append(
            f"{u['user_id']} | @{u.get('username') or '-'} | "
            f"{u.get('first_name') or '-'} | {'BANNED' if u.get('banned') else 'ok'}"
        )
    await safe_call(client.send_message, chat_id, f"👥 Total: <b>{total}</b> | 🚫 Banned: <b>{banned}</b>")
    if lines:
        bio = io.BytesIO("\n".join(lines).encode("utf-8"))
        bio.name = "users.txt"
        await safe_call(client.send_document, chat_id, bio, caption="Full user list")


# ------------------------------------------------------------ rate limiter --
class RateLimiter:
    """Sliding-window limiter. Exceeding it triggers a temporary block."""

    def __init__(self, max_messages: int, window: int, block_seconds: int):
        self.max = max_messages
        self.window = window
        self.block = block_seconds
        self._hits: Dict[int, deque] = defaultdict(deque)
        self._blocked_until: Dict[int, float] = {}

    def check(self, user_id: int) -> str:
        """Returns 'ok', 'just_blocked' (first violation) or 'blocked'."""
        now = time.monotonic()
        until = self._blocked_until.get(user_id)
        if until:
            if now < until:
                return "blocked"
            del self._blocked_until[user_id]
            self._hits.pop(user_id, None)

        hits = self._hits[user_id]
        hits.append(now)
        while hits and now - hits[0] > self.window:
            hits.popleft()

        if len(hits) > self.max:
            self._blocked_until[user_id] = now + self.block
            hits.clear()
            return "just_blocked"
        return "ok"


limiter = RateLimiter(config.FLOOD_MAX_MESSAGES, config.FLOOD_WINDOW_SECONDS, config.FLOOD_BLOCK_SECONDS)


# --------------------------------------------------------------- delivery --
async def deliver_content(client, chat_id: int, token: str) -> bool:
    """Send the file/batch behind `token` to chat_id. Returns True on success."""
    collection = "files"
    doc = await db.get_file(token)
    if doc:
        ids = [doc["message_id"]]
    else:
        collection = "batches"
        doc = await db.get_batch(token)
        ids = doc["message_ids"] if doc else []

    if not ids:
        await safe_call(client.send_message, chat_id, "❌ This link is invalid or has expired.")
        return False

    sent: List[int] = []
    failed = 0

    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            messages = await safe_call(client.get_messages, config.DB_CHANNEL_ID, chunk)
        except RPCError:
            log.exception("get_messages failed for DB channel")
            failed += len(chunk)
            continue

        for msg in messages:
            if not msg or msg.empty:  # deleted from the DB channel
                failed += 1
                continue
            try:
                copied = await safe_call(msg.copy, chat_id, protect_content=config.PROTECT_CONTENT)
                sent.append(copied.id)
            except RPCError as exc:
                log.warning("Could not deliver message %s to %s: %s", msg.id, chat_id, exc)
                failed += 1
            if len(ids) > 1:
                await asyncio.sleep(0.3)  # gentle pacing for batches

    if not sent:
        await safe_call(client.send_message, chat_id, "❌ Sorry, these files are no longer available.")
        return False

    await db.inc_downloads(collection, token)

    if failed:
        await safe_call(client.send_message, chat_id, f"⚠️ {failed} item(s) could not be delivered.")

    if config.AUTO_DELETE_SECONDS > 0:
        tail = (
            "Please download them before then."
            if config.PROTECT_CONTENT
            else "Forward them to Saved Messages before then."
        )
        notice = await safe_call(
            client.send_message,
            chat_id,
            f"⚠️ <b>Heads up!</b> These files will be deleted in "
            f"<b>{humanize(config.AUTO_DELETE_SECONDS)}</b>. {tail}\n"
            "You can re-open the link any time to get them again.",
        )
        await db.schedule_deletion(
            chat_id, sent + [notice.id], time.time() + config.AUTO_DELETE_SECONDS, token
        )
    return True

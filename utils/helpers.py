"""
utils/helpers.py - Shared helpers.

  * custom filters (admin_only, media_filter, batch_filter) + batch session store
  * safe_call(): retries on FloodWait
  * RateLimiter: sliding-window anti-flood
  * token / link helpers
  * deliver_content(): copies stored files to a user and schedules auto-delete
"""
import asyncio
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

ADMIN_HELP = (
    "🛠 <b>Admin panel</b>\n\n"
    "📤 Send any file → get a shareable link\n"
    "/batch → collect many files, then /done for one link (/cancel to abort)\n"
    "/stats → bot statistics\n"
    "/users → user count + full list file\n"
    "/broadcast → reply to a message to send it to all users\n"
    "/ban <code>&lt;id&gt; [reason]</code> · /unban <code>&lt;id&gt;</code>"
)

# ---------------------------------------------------------------- filters --
batch_sessions: Dict[int, List[int]] = {}  # admin_id -> list of DB-channel message IDs


async def _is_admin(_, __, message) -> bool:
    return bool(message.from_user and message.from_user.id in config.ADMINS)


async def _in_batch(_, __, message) -> bool:
    return bool(message.from_user and message.from_user.id in batch_sessions)


admin_only = filters.create(_is_admin)
batch_filter = filters.create(_in_batch)
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

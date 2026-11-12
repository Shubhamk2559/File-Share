"""
database/mongo.py - Async MongoDB helpers (motor).

Collections:
  users      {user_id, first_name, username, banned, ban_reason, joined_at, last_seen}
  files      {token, message_id, kind, file_name, file_size, created_by, created_at, downloads}
  batches    {token, message_ids[], created_by, created_at, downloads}
  deletions  {chat_id, message_ids[], delete_at, token}   <- persistent auto-delete queue

A small in-memory cache of banned IDs avoids a DB round-trip on every message.
"""
import logging
import time
from typing import AsyncIterator, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

import config

log = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None

banned_cache: set = set()
_known_users: set = set()


async def init() -> None:
    """Connect, verify the connection, create indexes, warm the ban cache."""
    global _client, _db
    _client = AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=10_000)
    _db = _client[config.MONGO_DB_NAME]
    await _client.admin.command("ping")  # raises if unreachable

    await _db.users.create_index("user_id", unique=True)
    await _db.files.create_index("token", unique=True)
    await _db.batches.create_index("token", unique=True)
    await _db.deletions.create_index("delete_at")

    async for doc in _db.users.find({"banned": True}, {"user_id": 1}):
        banned_cache.add(doc["user_id"])
    log.info("MongoDB connected (db=%s, banned users cached=%d)", config.MONGO_DB_NAME, len(banned_cache))


async def close() -> None:
    if _client:
        _client.close()


# ------------------------------------------------------------------ users --
async def add_user(user_id: int, first_name: Optional[str], username: Optional[str]) -> bool:
    """Upsert a user. Returns True if the user is new. Cached to limit writes."""
    if user_id in _known_users:
        return False
    now = time.time()
    res = await _db.users.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {"user_id": user_id, "banned": False, "joined_at": now},
            "$set": {"first_name": first_name, "username": username, "last_seen": now},
        },
        upsert=True,
    )
    _known_users.add(user_id)
    return res.upserted_id is not None


async def remove_user(user_id: int) -> None:
    _known_users.discard(user_id)
    banned_cache.discard(user_id)
    await _db.users.delete_one({"user_id": user_id})


def is_banned(user_id: int) -> bool:
    return user_id in banned_cache


async def ban_user(user_id: int, reason: str = "") -> None:
    await _db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {"banned": True, "ban_reason": reason},
            "$setOnInsert": {"user_id": user_id, "joined_at": time.time()},
        },
        upsert=True,
    )
    banned_cache.add(user_id)


async def unban_user(user_id: int) -> bool:
    res = await _db.users.update_one({"user_id": user_id}, {"$set": {"banned": False, "ban_reason": ""}})
    banned_cache.discard(user_id)
    return res.matched_count > 0


async def count_users() -> int:
    return await _db.users.count_documents({})


async def count_banned() -> int:
    return await _db.users.count_documents({"banned": True})


async def iter_users() -> AsyncIterator[Dict]:
    async for doc in _db.users.find({}).sort("joined_at", 1):
        yield doc


async def iter_user_ids() -> AsyncIterator[int]:
    """All non-banned user IDs (used for broadcasts)."""
    async for doc in _db.users.find({"banned": {"$ne": True}}, {"user_id": 1}):
        yield doc["user_id"]


# ------------------------------------------------------------ files/batches --
async def create_file(token: str, message_id: int, kind: str, file_name: str,
                      file_size: int, created_by: int) -> None:
    await _db.files.insert_one({
        "token": token, "message_id": message_id, "kind": kind,
        "file_name": file_name, "file_size": file_size,
        "created_by": created_by, "created_at": time.time(), "downloads": 0,
    })


async def get_file(token: str) -> Optional[Dict]:
    return await _db.files.find_one({"token": token})


async def create_batch(token: str, message_ids: List[int], created_by: int) -> None:
    await _db.batches.insert_one({
        "token": token, "message_ids": message_ids,
        "created_by": created_by, "created_at": time.time(), "downloads": 0,
    })


async def get_batch(token: str) -> Optional[Dict]:
    return await _db.batches.find_one({"token": token})


async def inc_downloads(collection: str, token: str) -> None:
    """collection is 'files' or 'batches'."""
    await _db[collection].update_one({"token": token}, {"$inc": {"downloads": 1}})


async def get_stats() -> Dict[str, int]:
    async def _downloads(col: str) -> int:
        cursor = _db[col].aggregate([{"$group": {"_id": None, "n": {"$sum": "$downloads"}}}])
        rows = await cursor.to_list(length=1)
        return rows[0]["n"] if rows else 0

    return {
        "users": await count_users(),
        "banned": await count_banned(),
        "files": await _db.files.count_documents({}),
        "batches": await _db.batches.count_documents({}),
        "downloads": await _downloads("files") + await _downloads("batches"),
        "pending_deletions": await _db.deletions.count_documents({}),
    }


# --------------------------------------------------------------- deletions --
async def schedule_deletion(chat_id: int, message_ids: List[int], delete_at: float,
                            token: Optional[str] = None) -> None:
    await _db.deletions.insert_one({
        "chat_id": chat_id, "message_ids": message_ids,
        "delete_at": delete_at, "token": token,
    })


async def pop_due_deletion(now: float) -> Optional[Dict]:
    """Atomically claim (and remove) the oldest due job so it is never run twice."""
    return await _db.deletions.find_one_and_delete(
        {"delete_at": {"$lte": now}}, sort=[("delete_at", 1)]
    )

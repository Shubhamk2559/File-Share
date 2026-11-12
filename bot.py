"""
bot.py - Entry point.

Responsibilities:
  * configure logging (console + rotating file)
  * connect to MongoDB
  * start the Pyrogram client (handlers are auto-loaded from ./handlers)
  * validate the DB channel and force-sub channels
  * run the background auto-delete scheduler
"""
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from pyrogram import Client, idle
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError

import config
from database import mongo as db
from utils import force_sub
from utils.scheduler import run_scheduler

log = logging.getLogger("bot")


def setup_logging() -> None:
    """Log to console and to logs/bot.log (5 MB x 3 rotating files)."""
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        config.LOG_DIR / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Pyrogram is very chatty at INFO level
    logging.getLogger("pyrogram").setLevel(logging.WARNING)


async def verify_db_channel(app: Client) -> None:
    """Fail fast with a helpful message if the DB channel is not usable."""
    try:
        await app.get_chat(config.DB_CHANNEL_ID)
        member = await app.get_chat_member(config.DB_CHANNEL_ID, "me")
    except RPCError as exc:
        raise RuntimeError(
            f"Cannot access DB channel {config.DB_CHANNEL_ID}: {exc}. "
            "Make sure the ID starts with -100 and the bot was added to the channel as admin."
        ) from exc

    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        raise RuntimeError(
            "The bot is not an administrator of the DB channel. "
            "Promote it with the 'Post messages' permission."
        )


async def main() -> None:
    setup_logging()
    log.info("Starting file sharing bot...")

    await db.init()

    app = Client(
        name="filesharebot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workdir=str(config.SESSION_DIR),
        plugins={"root": "handlers"},      # auto-load every module in ./handlers
        parse_mode=ParseMode.HTML,
        sleep_threshold=30,                # Pyrogram auto-sleeps on FloodWait <= 30s
    )

    scheduler_task = None
    await app.start()
    try:
        await verify_db_channel(app)
        await force_sub.load_channels(app)
        scheduler_task = asyncio.create_task(run_scheduler(app))
        log.info("Bot @%s is up and running.", app.me.username)
        await idle()
    finally:
        log.info("Shutting down...")
        if scheduler_task:
            scheduler_task.cancel()
        await app.stop()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception:
        logging.getLogger("bot").exception("Fatal error")
        sys.exit(1)

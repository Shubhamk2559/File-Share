"""
utils/ui.py - All menu texts and keyboards (so every command is reachable by button).

Style: bold-italic UPPERCASE text, blockquotes, coloured-looking button rows.
All bot-facing text is English.
"""
import html

from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

import config
from utils import force_sub
from utils.helpers import humanize


_INTRO = (
    "I AM A PERMANENT FILE STORE BOT AND USERS CAN ACCESS STORED MESSAGES "
    "BY USING A SHAREABLE LINK GIVEN BY ME."
)


def _s(text: str) -> str:
    """Bold + italic wrapper used for the uppercase style."""
    return f"<b><i>{text}</i></b>"


# ---------------------------------------------------------------- start --
def welcome_text(user, bot) -> str:
    name = html.escape(user.first_name or "there")
    return (
        f"{_s('HEY')} <a href=\"tg://user?id={user.id}\">{name}</a>,\n\n"
        f"<blockquote>{_s('MY NAME IS')} "
        f"<a href=\"https://t.me/{bot.username}\">{html.escape(bot.first_name)}</a></blockquote>\n\n"
        f"{_s(_INTRO)}\n\n"
        f"<blockquote>{_s('TO KNOW MORE CLICK HELP BUTTON.')}</blockquote>"
    )


def home_markup(is_admin: bool) -> Markup:
    rows = [[Btn("🕵️ HELP", callback_data="menu:help"), Btn("📜 ABOUT", callback_data="menu:about")]]
    if is_admin:
        rows.append([Btn("‼️ SETTINGS ‼️", callback_data="menu:settings")])
    return Markup(rows)


# ----------------------------------------------------------------- help --
def help_text(is_admin: bool) -> str:
    if not is_admin:
        return (
            f"{_s('HOW TO USE ME')}\n\n"
            f"<blockquote>{_s('1. OPEN A FILE LINK SHARED WITH YOU.')}\n"
            f"{_s('2. JOIN THE REQUIRED CHANNELS IF ASKED, THEN PRESS TRY AGAIN.')}\n"
            f"{_s('3. SAVE YOUR FILES BEFORE THEY ARE AUTO-DELETED.')}</blockquote>"
        )
    return (
        f"{_s('ADMIN TOOLS')}\n\n"
        f"<blockquote>{_s('SEND ANY FILE TO ME TO GET A SHAREABLE LINK.')}\n"
        f"{_s('USE THE BUTTONS BELOW FOR EVERYTHING ELSE.')}</blockquote>"
    )


def help_markup(is_admin: bool) -> Markup:
    rows = []
    if is_admin:
        rows += [
            [Btn("📊 STATS", callback_data="adm:stats"), Btn("👥 USERS", callback_data="adm:users")],
            [Btn("📦 BATCH", callback_data="adm:batch"), Btn("📢 BROADCAST", callback_data="adm:broadcast")],
            [Btn("🚫 BAN USER", callback_data="adm:ban"), Btn("✅ UNBAN USER", callback_data="adm:unban")],
        ]
    rows.append([Btn("🆔 MY ID", callback_data="usr:id")])
    rows.append([Btn("⬅️ BACK", callback_data="menu:home")])
    return Markup(rows)


# ---------------------------------------------------------------- about --
def about_text(bot) -> str:
    return (
        f"{_s('ABOUT')}\n\n"
        f"<blockquote>{_s('BOT')}: <a href=\"https://t.me/{bot.username}\">{html.escape(bot.first_name)}</a>\n"
        f"{_s('FILES ARE STORED SAFELY AND SHARED WITH PERMANENT LINKS.')}\n"
        f"{_s('SINGLE FILES AND BATCH LINKS SUPPORTED.')}</blockquote>"
    )


# ------------------------------------------------------------- settings --
def settings_text() -> str:
    auto = humanize(config.AUTO_DELETE_SECONDS) if config.AUTO_DELETE_SECONDS else "OFF"
    return (
        f"{_s('SETTINGS')}\n\n"
        f"<blockquote>⏱ {_s('AUTO DELETE')}: <b>{auto.upper()}</b>\n"
        f"🔐 {_s('PROTECT CONTENT')}: <b>{'ON' if config.PROTECT_CONTENT else 'OFF'}</b>\n"
        f"📢 {_s('FORCE SUBSCRIBE')}: <b>{len(force_sub.channels)} CHANNEL(S)</b>\n"
        f"📦 {_s('MAX BATCH SIZE')}: <b>{config.MAX_BATCH_SIZE}</b>\n"
        f"🛡 {_s('FLOOD LIMIT')}: <b>{config.FLOOD_MAX_MESSAGES} MSG / {config.FLOOD_WINDOW_SECONDS}s</b></blockquote>\n\n"
        f"{_s('THESE VALUES ARE CHANGED IN THE ENVIRONMENT VARIABLES.')}"
    )


def back_markup(target: str = "home") -> Markup:
    return Markup([[Btn("⬅️ BACK", callback_data=f"menu:{target}")]])


# --------------------------------------------------------- admin prompts --
def batch_markup() -> Markup:
    return Markup([[Btn("✅ DONE", callback_data="bt:done"), Btn("❌ CANCEL", callback_data="bt:cancel")]])


def cancel_markup() -> Markup:
    return Markup([[Btn("❌ CANCEL", callback_data="ask:cancel")]])


def confirm_broadcast_markup() -> Markup:
    return Markup([[Btn("✅ SEND TO ALL", callback_data="bc:yes"), Btn("❌ CANCEL", callback_data="bc:no")]])

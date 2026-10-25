import os
import json
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.errors import AuthKeyDuplicated, MessageNotModified, UserNotParticipant
import redis
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# 1. Acquire API ID and API Hash from https://my.telegram.org/apps
api_id = int(os.environ.get("TELEGRAM_API_ID"))
api_hash = os.environ.get("TELEGRAM_API_HASH")

# 2. Token from @BotFather
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

# 3. Owner username
owner_username = os.environ.get("OWNER_USERNAME")

# Redis connection
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

# Directory for Pyrogram's session file (holds the auth key). Mount it as a
# volume so restarts reuse the session instead of creating a new auth key
# (repeated key creation can get throttled by Telegram).
session_dir = os.environ.get("SESSION_DIR", ".")

# Create Pyrogram client with session name "my_bot"
# sleep_threshold: auto-wait out Telegram flood limits (FLOOD_WAIT) up to this
# many seconds instead of raising, so large @all mentions still get delivered.
app = Client(
    "my_bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token,
    workdir=session_dir,
    sleep_threshold=60
)

# Per-chat settings. A chat that never changed them keeps the original
# behaviour: anyone can use @all, and it mentions every member except the
# excluded ones.
#   who:  "everyone" | "admins" (admins plus users allowed with /allow)
#   whom: "all"      | "list"   (only users added with /include)
SETTINGS_DEFAULTS = {"who": "everyone", "whom": "all"}

GROUP_ONLY_TEXT = (
    "⚠️ This command only works in groups!\n\n"
    "Add me to a group and try again."
)
NO_PERMISSION_TEXT = (
    "⛔ You don't have permission to use this. In this chat only admins "
    "and users they allow can mention everyone."
)


def get_setting(chat_id: int, name: str) -> str:
    return redis_client.hget(f"settings:{chat_id}", name) or SETTINGS_DEFAULTS[name]


def set_setting(chat_id: int, name: str, value: str):
    redis_client.hset(f"settings:{chat_id}", name, value)


def excluded_key(chat_id: int) -> str:
    return f"excluded_users:{chat_id}"


def mention_list_key(chat_id: int) -> str:
    return f"mention_list:{chat_id}"


def allowed_key(chat_id: int) -> str:
    return f"allowed_users:{chat_id}"


def user_ids(key: str) -> set:
    return {int(member) for member in redis_client.smembers(key)}


def get_excluded_users(chat_id: int) -> set:
    """Get list of excluded users for the chat"""
    return user_ids(excluded_key(chat_id))


def remember_user(user):
    """Keep the user's name so lists can be shown and mentioned without
    resolving them through Telegram again."""
    redis_client.hset("user_names", user.id, json.dumps(
        {"username": user.username, "first_name": user.first_name}
    ))


def stored_user(user_id: int) -> dict:
    raw = redis_client.hget("user_names", user_id)
    return json.loads(raw) if raw else {}


def display_name(user_id: int, username=None, first_name=None) -> str:
    # No "@" on purpose: replies would ping the user.
    return username or first_name or f"ID {user_id}"


def format_mention(user_id: int, username=None, first_name=None) -> str:
    if username:
        return f"@{username}"
    return f"[{first_name or 'NoName'}](tg://user?id={user_id})"


async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await app.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        return False


async def sender_is_admin(message: Message) -> bool:
    # Anonymous admins post on behalf of the group itself and have no from_user.
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if not message.from_user:
        return False
    return await is_admin(message.chat.id, message.from_user.id)


async def can_mention_all(message: Message) -> bool:
    if get_setting(message.chat.id, "who") != "admins":
        return True
    if message.from_user and redis_client.sismember(allowed_key(message.chat.id), message.from_user.id):
        return True
    return await sender_is_admin(message)


async def check_group_admin(message: Message) -> bool:
    """Reply and return False unless this is a group and the sender is an admin."""
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(GROUP_ONLY_TEXT)
        return False
    if not await sender_is_admin(message):
        await message.reply_text("This command is only available to administrators.")
        return False
    return True


async def for_each_target(message: Message, verb: str, action):
    """Apply action(user) to the replied-to user or to every @username / ID
    given after the command, and reply with one line per user."""
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        if not user:
            await message.reply_text("Can't tell who wrote that message. Specify their @username instead.")
            return
        targets = [user]
    elif len(message.command) >= 2:
        targets = message.command[1:]
    else:
        await message.reply_text("Reply to a user's message or specify their @username")
        return

    lines = []
    for target in targets:
        label = target if isinstance(target, str) else display_name(target.id, target.username, target.first_name)
        try:
            if isinstance(target, str):
                ref = target.lstrip("@")
                target = await app.get_users(int(ref) if ref.lstrip("-").isdigit() else ref)
            remember_user(target)
            lines.append(action(target))
        except Exception as e:
            lines.append(f"Failed to {verb} {label}: {str(e)}")
    # Names are user-controlled: send them as plain text.
    await message.reply_text("\n".join(lines), parse_mode=ParseMode.DISABLED)


@app.on_message(filters.command(["exclude"]))
async def exclude_user(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id
    list_mode = get_setting(chat_id, "whom") == "list"

    def action(user):
        name = display_name(user.id, user.username, user.first_name)
        if list_mode:
            redis_client.srem(mention_list_key(chat_id), user.id)
            return f"User {name} has been removed from the mention list"
        redis_client.sadd(excluded_key(chat_id), user.id)
        return f"User {name} has been excluded from @all mentions"

    await for_each_target(message, "exclude", action)


@app.on_message(filters.command(["include"]))
async def include_user(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id
    list_mode = get_setting(chat_id, "whom") == "list"

    def action(user):
        name = display_name(user.id, user.username, user.first_name)
        if list_mode:
            redis_client.sadd(mention_list_key(chat_id), user.id)
            return f"User {name} has been added to the mention list"
        redis_client.srem(excluded_key(chat_id), user.id)
        return f"User {name} will now receive @all mentions again"

    await for_each_target(message, "include", action)


@app.on_message(filters.command(["allow"]))
async def allow_user(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id
    note = "" if get_setting(chat_id, "who") == "admins" else " (takes effect after /whocan admins)"

    def action(user):
        redis_client.sadd(allowed_key(chat_id), user.id)
        return f"User {display_name(user.id, user.username, user.first_name)} can now use @all{note}"

    await for_each_target(message, "allow", action)


@app.on_message(filters.command(["disallow"]))
async def disallow_user(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id

    def action(user):
        redis_client.srem(allowed_key(chat_id), user.id)
        return f"User {display_name(user.id, user.username, user.first_name)} is no longer allowed to use @all"

    await for_each_target(message, "disallow", action)


@app.on_message(filters.command(["excluded"]))
async def list_excluded(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id

    try:
        excluded_users = get_excluded_users(chat_id)
        if not excluded_users:
            await message.reply_text("The list of excluded users is empty.")
            return

        text = "Excluded users:\n"
        for user_id in excluded_users:
            try:
                user = await app.get_users(user_id)
                text += f"- {user.username or user.first_name} (ID: {user.id})\n"
            except:
                text += f"- Unknown User (ID: {user_id})\n"

        await message.reply_text(text)
    except Exception as e:
        await message.reply_text(f"Error getting excluded users list: {str(e)}")


WHO_CHOICES = {"admins": "Admins only", "everyone": "Everyone"}
WHOM_CHOICES = {"list": "Only the list", "all": "All members"}


def setting_buttons(chat_id: int, name: str, view: str) -> list:
    """One keyboard row for a setting; the current choice is ticked.
    view says which message to redraw after a tap: "single" or "settings"."""
    choices = WHO_CHOICES if name == "who" else WHOM_CHOICES
    current = get_setting(chat_id, name)
    return [
        InlineKeyboardButton(("✅ " if value == current else "") + label, callback_data=f"set:{name}:{value}:{view}")
        for value, label in choices.items()
    ]


def who_text(chat_id: int) -> str:
    current = "admins and allowed users" if get_setting(chat_id, "who") == "admins" else "everyone"
    return (
        f"Who can use @all now: {current}.\n\n"
        "/whocan admins - only admins and users allowed with /allow\n"
        "/whocan everyone - every member"
    )


def whom_text(chat_id: int) -> str:
    if get_setting(chat_id, "whom") == "list":
        current = f"only the mention list ({redis_client.scard(mention_list_key(chat_id))})"
    else:
        current = "all members except excluded users"
    return (
        f"Who gets mentioned now: {current}.\n\n"
        "/mentionmode list - only people added with /include\n"
        "/mentionmode all - all members except excluded users"
    )


def describe_users(title: str, ids: set, limit: int = 30) -> str:
    if not ids:
        return f"{title}: none"
    names = []
    for user_id in sorted(ids)[:limit]:
        info = stored_user(user_id)
        names.append(display_name(user_id, info.get("username"), info.get("first_name"))[:32])
    more = f" and {len(ids) - limit} more" if len(ids) > limit else ""
    return f"{title} ({len(ids)}): " + ", ".join(names) + more


def settings_text(chat_id: int) -> str:
    admins_only = get_setting(chat_id, "who") == "admins"
    list_mode = get_setting(chat_id, "whom") == "list"
    return (
        "⚙️ Settings for this chat\n\n"
        f"Who can use @all: {'admins and allowed users' if admins_only else 'everyone'} (/whocan)\n"
        f"Who gets mentioned: {'only the mention list' if list_mode else 'all members except excluded users'} (/mentionmode)\n\n"
        + describe_users("Allowed users", user_ids(allowed_key(chat_id))) + "\n"
        + describe_users("Mention list", user_ids(mention_list_key(chat_id))) + "\n"
        + describe_users("Excluded users", get_excluded_users(chat_id))
    )


def settings_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        setting_buttons(chat_id, "who", "settings"),
        setting_buttons(chat_id, "whom", "settings"),
    ])


@app.on_message(filters.command(["whocan"]))
async def set_who(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id
    choice = message.command[1].lower() if len(message.command) > 1 else ""

    if choice == "admins":
        set_setting(chat_id, "who", "admins")
        await message.reply_text(
            "✅ Now only admins and allowed users can use @all.\n"
            "Allow someone with /allow @username (or reply to their message)."
        )
    elif choice == "everyone":
        set_setting(chat_id, "who", "everyone")
        await message.reply_text("✅ Everyone can use @all again.")
    else:
        # Tapping /whocan in a message sends it without an argument: offer buttons.
        await message.reply_text(
            who_text(chat_id),
            reply_markup=InlineKeyboardMarkup([setting_buttons(chat_id, "who", "single")])
        )


@app.on_message(filters.command(["mentionmode"]))
async def set_whom(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id
    choice = message.command[1].lower() if len(message.command) > 1 else ""

    if choice == "list":
        set_setting(chat_id, "whom", "list")
        count = redis_client.scard(mention_list_key(chat_id))
        await message.reply_text(
            f"✅ @all now mentions only the people on the mention list ({count}).\n"
            "Add people with /include @username, remove them with /exclude @username."
        )
    elif choice == "all":
        set_setting(chat_id, "whom", "all")
        await message.reply_text(
            "✅ @all mentions all members again (except excluded users).\n"
            "Stop mentioning someone with /exclude @username, see the list with /excluded."
        )
    else:
        await message.reply_text(
            whom_text(chat_id),
            reply_markup=InlineKeyboardMarkup([setting_buttons(chat_id, "whom", "single")])
        )


@app.on_message(filters.command(["settings"]))
async def show_settings(client: Client, message: Message):
    if not await check_group_admin(message):
        return
    chat_id = message.chat.id
    await message.reply_text(
        settings_text(chat_id),
        parse_mode=ParseMode.DISABLED,
        reply_markup=settings_keyboard(chat_id)
    )


@app.on_callback_query(filters.regex(r"^set:(who|whom):(\w+):(single|settings)$"))
async def settings_button(client: Client, callback: CallbackQuery):
    _, name, value, view = callback.data.split(":")
    message = callback.message
    choices = WHO_CHOICES if name == "who" else WHOM_CHOICES
    if message is None or value not in choices:
        await callback.answer()
        return
    chat_id = message.chat.id

    if not await is_admin(chat_id, callback.from_user.id):
        await callback.answer("Only admins can change these settings.", show_alert=True)
        return
    if get_setting(chat_id, name) == value:
        await callback.answer("Already set.")
        return

    set_setting(chat_id, name, value)
    await callback.answer(f"✅ {choices[value]}")
    try:
        if view == "settings":
            await message.edit_text(settings_text(chat_id), parse_mode=ParseMode.DISABLED,
                                    reply_markup=settings_keyboard(chat_id))
        elif name == "who":
            await message.edit_text(who_text(chat_id),
                                    reply_markup=InlineKeyboardMarkup([setting_buttons(chat_id, "who", "single")]))
        else:
            await message.edit_text(whom_text(chat_id),
                                    reply_markup=InlineKeyboardMarkup([setting_buttons(chat_id, "whom", "single")]))
    except MessageNotModified:
        pass
    except Exception as e:
        # The setting is saved either way; the old message may just be gone.
        log.warning(f"Couldn't refresh settings message: {type(e).__name__}: {e}")


HELP_TEXT = f"""
👋 Hello! I'm a bot that helps mention all members in a group.

Commands:
• /all or @all - Mention all members in the group
• /exclude - Exclude user from @all mentions (admin only)
• /include - Include previously excluded user (admin only)
• /excluded - Show list of excluded users (admin only)
• /info - Show this help message

Settings (admin only):
• /settings - Show this chat's settings
• /whocan admins - Only admins and allowed users can use @all (/whocan everyone to undo)
• /allow, /disallow - Let a user use @all when /whocan admins is on
• /mentionmode list - Mention only a chosen list of people instead of all members (/mentionmode all to undo)

In list mode /include adds a user to the list and /exclude removes them. Excluded users are kept and are skipped again after /mentionmode all.

How to choose users for /exclude, /include, /allow and /disallow:
• send the command as a reply to the user's message, or
• write usernames after the command, separated by spaces: `/include @username1 @username2`

Note: I only work in groups, not in private chats!

For questions and support, contact {owner_username}
"""

@app.on_message(filters.command(["start", "info"]))
async def show_info(client: Client, message: Message):
    await message.reply_text(HELP_TEXT)


async def member_mentions(client: Client, chat_id: int, from_user) -> list:
    """Everyone in the chat except bots, the caller and excluded users."""
    excluded_users = get_excluded_users(chat_id)
    mentions = []
    async for member in client.get_chat_members(chat_id):
        user = member.user

        # Skip bots
        if user.is_bot:
            continue

        # Skip author of the command
        if from_user and user.id == from_user.id:
            continue

        # Skip excluded users
        if user.id in excluded_users:
            continue

        mentions.append(format_mention(user.id, user.username, user.first_name))
    return mentions


async def list_mentions(client: Client, chat_id: int, from_user) -> list:
    """Only the users on the chat's mention list who are still in the chat."""
    mentions = []
    for user_id in sorted(user_ids(mention_list_key(chat_id))):
        if from_user and user_id == from_user.id:
            continue
        try:
            member = await client.get_chat_member(chat_id, user_id)
        except UserNotParticipant:
            continue
        except Exception:
            # Telegram couldn't resolve the user right now (e.g. the session's
            # peer cache lost them): fall back to the name saved by /include.
            info = stored_user(user_id)
            mentions.append(format_mention(user_id, info.get("username"), info.get("first_name")))
            continue
        if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            continue
        remember_user(member.user)
        mentions.append(format_mention(user_id, member.user.username, member.user.first_name))
    return mentions


async def send_mentions(message: Message, mentions: list):
    max_length = 4096
    chunks = []
    current_chunk = ""
    for mention in mentions:
        if current_chunk and len(current_chunk) + 1 + len(mention) > max_length:
            chunks.append(current_chunk)
            current_chunk = mention
        else:
            current_chunk = f"{current_chunk} {mention}" if current_chunk else mention
    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        # Small pause between chunks to avoid tripping Telegram's flood limit
        if i > 0:
            await asyncio.sleep(2)
        await message.reply_text(
            chunk,
            disable_web_page_preview=True,
            quote=(i == 0)
        )


# Whole word only: a bare r"@all" also matched @allah, @alliance_chat,
# @all_news... and mass-mentioned the group by accident.
@app.on_message(filters.command(["all"]) | filters.regex(r"(?<!\w)@all\b"))
async def mention_all(client, message):
    chat_id = message.chat.id

    # Check if it's a group chat
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "⚠️ This bot only works in groups!\n\n"
            "Add me to a group and use /all or @all to mention all members."
        )
        return

    if not await can_mention_all(message):
        await message.reply_text(NO_PERMISSION_TEXT)
        return

    try:
        if get_setting(chat_id, "whom") == "list":
            if not redis_client.scard(mention_list_key(chat_id)):
                await message.reply_text(
                    "No one to mention: the mention list is empty.\n"
                    "Admins can add people with /include @username."
                )
                return
            mentions = await list_mentions(client, chat_id, message.from_user)
        else:
            mentions = await member_mentions(client, chat_id, message.from_user)

        if not mentions:
            await message.reply_text("No suitable members found to mention.")
        else:
            await send_mentions(message, mentions)
    except Exception as e:
        await message.reply_text(f"Failed to mention members: {str(e)}")

# Health check interval and tolerance
HEALTHCHECK_INTERVAL = 60   # seconds between checks
HEALTHCHECK_TIMEOUT = 20    # seconds to wait for a single check
HEALTHCHECK_MAX_FAILURES = 3  # consecutive failures before forcing a restart
SESSION_SAVE_EVERY = 10     # healthchecks between session commits (~10 min)


async def watchdog():
    """Actively probe the Telegram connection.

    Pyrogram keeps the connection alive in background tasks, so a dead
    socket never raises inside main() — it just logs "Connection lost"
    forever while the process stays up. We periodically make a real
    round-trip request; if it keeps failing, the connection is wedged and
    the only reliable fix is a fresh process (Docker's restart policy
    brings us back). This is the automatic equivalent of a manual restart.

    It also commits the session file now and then: Pyrogram writes the peer
    cache (users/chats and their access hashes) without committing and only
    commits on a clean stop, which a container restart never is — so every
    restart used to roll the cache back to the last clean stop.
    """
    failures = 0
    checks = 0
    while True:
        await asyncio.sleep(HEALTHCHECK_INTERVAL)
        try:
            await asyncio.wait_for(app.get_me(), timeout=HEALTHCHECK_TIMEOUT)
            if failures:
                log.info("Healthcheck recovered.")
            failures = 0
            checks += 1
            if checks % SESSION_SAVE_EVERY == 0:
                try:
                    await app.storage.save()
                except Exception as e:
                    log.warning(f"Session save failed: {type(e).__name__}: {e}")
        except Exception as e:
            failures += 1
            log.warning(
                f"Healthcheck failed ({failures}/{HEALTHCHECK_MAX_FAILURES}): "
                f"{type(e).__name__}: {e}"
            )
            if failures >= HEALTHCHECK_MAX_FAILURES:
                log.error("Connection appears dead — exiting for a fresh restart.")
                try:
                    await asyncio.wait_for(app.stop(), timeout=10)
                except Exception:
                    pass
                # Hard-exit: the internal session is wedged, so don't rely on
                # a clean shutdown. Docker (restart: unless-stopped) restarts us.
                os._exit(1)


async def reset_client():
    """Tear the client down completely, whatever state a failed start left.

    app.stop() only works on a fully started client. If app.start() fails
    after connecting (e.g. its get_me() call times out), stop() raises
    "already terminated" and the client stays connected — every later
    app.start() then fails with "Client is already connected" and the bot
    never recovers. Such a half-started client must be disconnected directly.
    """
    try:
        if app.is_initialized:
            await app.stop()
        elif app.is_connected:
            await app.disconnect()
    except Exception as e:
        log.warning(f"Client cleanup failed: {type(e).__name__}: {e}")


# Bot start with auto-reconnect
async def main():
    backoff = 5
    max_backoff = 300  # 5 minutes max

    while True:
        try:
            log.info("Starting bot...")
            await app.start()
            log.info("Bot started successfully!")
            backoff = 5  # reset on successful start

            # Block here while actively watching the connection.
            await watchdog()

        except AuthKeyDuplicated:
            log.error("Auth key duplicated — session conflict. Exiting.")
            break

        except KeyboardInterrupt:
            log.info("Shutting down by user request.")
            break

        except Exception as e:
            log.error(f"Bot crashed: {type(e).__name__}: {e}")
            await reset_client()
            if app.is_connected or app.is_initialized:
                # Retrying in-process would fail forever; Docker
                # (restart: unless-stopped) brings us back as a fresh process.
                log.error("Client stuck half-started — exiting for a fresh restart.")
                os._exit(1)
            log.info(f"Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    await reset_client()

app.run(main())

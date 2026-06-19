import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.errors import AuthKeyDuplicated
import redis
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus, ChatType

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
app = Client(
    "my_bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token,
    workdir=session_dir
)

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await app.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        return False

def get_excluded_users(chat_id: int) -> set:
    """Get list of excluded users for the chat"""
    key = f"excluded_users:{chat_id}"
    members = redis_client.smembers(key)
    return {int(member) for member in members}

@app.on_message(filters.command(["exclude"]))
async def exclude_user(client: Client, message: Message):
    chat_id = message.chat.id

    # Check if it's a group chat
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "⚠️ This command only works in groups!\n\n"
            "Add me to a group and try again."
        )
        return
    
    if not await is_admin(chat_id, message.from_user.id):
        await message.reply_text("This command is only available to administrators.")
        return

    if not message.reply_to_message and len(message.command) < 2:
        await message.reply_text("Reply to a user's message or specify their @username")
        return

    try:
        if message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
            username = message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name
        else:
            username = message.command[1].replace("@", "")
            user = await app.get_users(username)
            user_id = user.id
            username = user.username or user.first_name

        key = f"excluded_users:{chat_id}"
        redis_client.sadd(key, user_id)
        await message.reply_text(f"User {username} has been excluded from @all mentions")
    except Exception as e:
        await message.reply_text(f"Failed to exclude user: {str(e)}")

@app.on_message(filters.command(["include"]))
async def include_user(client: Client, message: Message):
    chat_id = message.chat.id

    # Check if it's a group chat
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "⚠️ This command only works in groups!\n\n"
            "Add me to a group and try again."
        )
        return
    
    if not await is_admin(chat_id, message.from_user.id):
        await message.reply_text("This command is only available to administrators.")
        return

    if not message.reply_to_message and len(message.command) < 2:
        await message.reply_text("Reply to a user's message or specify their @username")
        return

    try:
        if message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
            username = message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name
        else:
            username = message.command[1].replace("@", "")
            user = await app.get_users(username)
            user_id = user.id
            username = user.username or user.first_name

        key = f"excluded_users:{chat_id}"
        redis_client.srem(key, user_id)
        await message.reply_text(f"User {username} will now receive @all mentions again")
    except Exception as e:
        await message.reply_text(f"Failed to include user: {str(e)}")

@app.on_message(filters.command(["excluded"]))
async def list_excluded(client: Client, message: Message):
    chat_id = message.chat.id

    # Check if it's a group chat
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "⚠️ This command only works in groups!\n\n"
            "Add me to a group and try again."
        )
        return
    
    if not await is_admin(chat_id, message.from_user.id):
        await message.reply_text("This command is only available to administrators.")
        return

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

HELP_TEXT = """
👋 Hello! I'm a bot that helps mention all members in a group.

Commands:
• /all or @all - Mention all members in the group
• /exclude - Exclude user from @all mentions (admin only)
• /include - Include previously excluded user (admin only)
• /excluded - Show list of excluded users (admin only)
• /info - Show this help message

Note: I only work in groups, not in private chats!

For questions and support, contact {owner_username}
"""

@app.on_message(filters.command(["start", "info"]))
async def show_info(client: Client, message: Message):
    await message.reply_text(HELP_TEXT)

@app.on_message(filters.command(["all"]) | filters.regex(r"@all"))
async def mention_all(client, message):
    chat_id = message.chat.id

    # Check if it's a group chat
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "⚠️ This bot only works in groups!\n\n"
            "Add me to a group and use /all or @all to mention all members."
        )
        return

    # Get list of excluded users
    excluded_users = get_excluded_users(chat_id)
    
    mentions = []
    from_user = message.from_user

    try:
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

            # If there is a username - use @username
            if user.username:
                mentions.append(f"@{user.username}")
            else:
                # Otherwise Markdown mention
                name = user.first_name or "NoName"
                mentions.append(f"[{name}](tg://user?id={user.id})")

        # Form the final text, splitting into chunks if needed
        if not mentions:
            await message.reply_text("No suitable members found to mention.")
        else:
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
                await message.reply_text(
                    chunk,
                    disable_web_page_preview=True,
                    quote=(i == 0)
                )
    except Exception as e:
        await message.reply_text(f"Failed to mention members: {str(e)}")

# Health check interval and tolerance
HEALTHCHECK_INTERVAL = 60   # seconds between checks
HEALTHCHECK_TIMEOUT = 20    # seconds to wait for a single check
HEALTHCHECK_MAX_FAILURES = 3  # consecutive failures before forcing a restart


async def watchdog():
    """Actively probe the Telegram connection.

    Pyrogram keeps the connection alive in background tasks, so a dead
    socket never raises inside main() — it just logs "Connection lost"
    forever while the process stays up. We periodically make a real
    round-trip request; if it keeps failing, the connection is wedged and
    the only reliable fix is a fresh process (Docker's restart policy
    brings us back). This is the automatic equivalent of a manual restart.
    """
    failures = 0
    while True:
        await asyncio.sleep(HEALTHCHECK_INTERVAL)
        try:
            await asyncio.wait_for(app.get_me(), timeout=HEALTHCHECK_TIMEOUT)
            if failures:
                log.info("Healthcheck recovered.")
            failures = 0
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
            log.info(f"Reconnecting in {backoff}s...")
            try:
                await app.stop()
            except Exception:
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    try:
        await app.stop()
    except Exception:
        pass

app.run(main())

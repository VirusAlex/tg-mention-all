import os
from pyrogram import Client, filters
import redis
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus, ChatType

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

# Create Pyrogram client with session name "my_bot"
app = Client(
    "my_bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
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

        # Form the final text
        text = " ".join(mentions)
        if text:
            await message.reply_text(
                text,
                disable_web_page_preview=True,
                quote=True
            )
        else:
            await message.reply_text("No suitable members found to mention.")
    except Exception as e:
        await message.reply_text(f"Failed to mention members: {str(e)}")

# Bot start
app.run()

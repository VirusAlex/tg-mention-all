# Mention All Bot

A Telegram bot that helps mention all members in a group chat. Built with Python and Pyrogram.

## Features

- Mention all members in a group using `/all` command or `@all` keyword
- Exclude specific users from mentions (admin only)
- Include previously excluded users (admin only)
- View list of excluded users (admin only)
- Works in group chats only
- Uses Redis for storing excluded users data
- Docker support for easy deployment

## Requirements

- Python 3.10+
- Docker and Docker Compose (for containerized deployment)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram API credentials (from [my.telegram.org/apps](https://my.telegram.org/apps))

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/mention_all_bot.git
cd mention_all_bot
```

2. Create `.env` file from example:
```bash
cp .env.example .env
```

3. Edit `.env` file with your credentials:
```env
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_USERNAME=@your_username
```

4. Build and run with Docker Compose:
```bash
docker-compose up -d
```

## Bot Commands

- `/all` or `@all` - Mention all members in the group
- `/exclude` - Exclude user from @all mentions (admin only)
- `/include` - Include previously excluded user (admin only)
- `/excluded` - Show list of excluded users (admin only)
- `/info` - Show help message

## Usage

1. Add the bot to your group
2. Use `/all` or `@all` (reply to a message) to mention all members
3. Administrators can use `/exclude` and `/include` to manage mentions

### Excluding Users

Administrators can exclude users in two ways:
- Reply to a user's message with `/exclude`
- Use `/exclude @username`

### Including Users

To add previously excluded users back:
- Reply to a user's message with `/include`
- Use `/include @username`

## Docker Deployment

The bot is containerized using Docker and includes:
- Python 3.10 slim base image
- Redis for data storage
- Automatic restart on failure
- Log rotation

### Container Management

Start the bot:
```bash
docker-compose up -d
```

View logs:
```bash
docker-compose logs -f bot
```

Stop the bot:
```bash
docker-compose down
```

## Troubleshooting

1. If the bot doesn't respond, check the logs:
```bash
docker-compose logs -f
```

2. If Redis connection fails, ensure the Redis container is running:
```bash
docker-compose ps
```

3. For permission issues, make sure the bot is an administrator in the group

## Contributing

Feel free to open issues and submit pull requests.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
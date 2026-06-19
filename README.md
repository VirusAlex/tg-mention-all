# Mention All Bot

A Telegram bot that helps mention all members in a group chat. Built with Python and Pyrogram.

[![Publish Docker image](https://github.com/VirusAlex/tg-mention-all/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/VirusAlex/tg-mention-all/actions/workflows/docker-publish.yml)
[![Docker image](https://img.shields.io/badge/ghcr.io-tg--mention--all-2496ED?logo=docker&logoColor=white)](https://github.com/VirusAlex/tg-mention-all/pkgs/container/tg-mention-all)
[![Python](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pyrogram](https://img.shields.io/badge/Pyrogram-2.0-FF8C00)](https://docs.pyrogram.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Features

- Mention all members in a group using `/all` command or `@all` keyword
- Long member lists are automatically split into multiple messages (4096-char limit)
- Exclude specific users from mentions (admin only)
- Include previously excluded users (admin only)
- View list of excluded users (admin only)
- Works in group chats only
- Uses Redis for storing excluded users data
- Self-healing: a connection watchdog restarts the bot if its Telegram session goes stale
- Docker support for easy deployment

## Requirements

- Python 3.10+
- Docker and Docker Compose (for containerized deployment)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram API credentials (from [my.telegram.org/apps](https://my.telegram.org/apps))

## Installation

1. Clone the repository:
```bash
git clone https://github.com/VirusAlex/tg-mention-all.git
cd tg-mention-all
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
- Python 3.10 Alpine base image (~76 MB)
- Redis for data storage
- Persistent Pyrogram session (stored in a Docker volume) so restarts reuse the
  auth key instead of creating a new one
- Automatic restart on failure, plus a connection watchdog that recovers stale sessions
- Log rotation

### Run with the pre-built image

A ready-to-use image is published to GitHub Container Registry on every push to `master`:
`ghcr.io/virusalex/tg-mention-all:latest`

The bot needs a Redis instance, so run both on a shared network:

```bash
docker network create mention_all_bot

docker run -d --name mention_all_bot_redis \
  --network mention_all_bot --restart unless-stopped \
  redis:alpine redis-server --appendonly yes

docker run -d --name mention_all_bot \
  --network mention_all_bot --restart unless-stopped \
  -v mention_all_bot_session:/data \
  -e TELEGRAM_API_ID=your_api_id \
  -e TELEGRAM_API_HASH=your_api_hash \
  -e TELEGRAM_BOT_TOKEN=your_bot_token \
  -e OWNER_USERNAME=@your_username \
  -e REDIS_HOST=mention_all_bot_redis \
  ghcr.io/virusalex/tg-mention-all:latest
```

The `-v mention_all_bot_session:/data` volume keeps the Pyrogram session (auth key)
across restarts. The session file is never baked into the image or committed to git.

For most setups Docker Compose (above) is simpler since it wires up Redis for you.

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
# Black Hole Discord Bot

Forum helper + crack/Denuvo notification bot for Discord, built with [py-cord](https://py-cord.dev/).

## Features

- `/forum help [channel] [user] [content]` — create a help post in any forum
- **Create Help Post** (message context menu) — right-click a message to create a help post from it
- `/solve` / `/close` — mark posts as solved or close them
- `/latest_cracks [amount]` — show recent voices38 cracks and Denuvo removals
- `/settings` — interactive panel to configure notifications, forums, permissions, and ping targets
- **Notification pings** — mention roles and members when new cracks/removals are posted

## Setup

### Prerequisites

- Python 3.11+
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))

### Local install

```bash
git clone https://github.com/YOUR_USERNAME/blackhole-bot.git
cd blackhole-bot
pip install -r requirements.txt
```

### Environment

Create a `.env` file in the project root:

```
DISCORD_TOKEN=your_token_here
```

### Run

```bash
python main.py
```

---

## VPS deployment (Linux)

Tested on Ubuntu 22.04 / Debian 12.

### 1. SSH into your VPS and clone the repo

```bash
sudo apt update && sudo apt install -y git python3 python3-pip python3-venv
git clone https://github.com/YOUR_USERNAME/blackhole-bot.git /opt/blackhole-bot
cd /opt/blackhole-bot
```

### 2. Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure the token

```bash
cp .env.example .env
nano .env   # paste your DISCORD_TOKEN, save and exit
```

### 4. Install the systemd service

```bash
sudo cp deploy/bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable blackhole-bot
sudo systemctl start blackhole-bot
```

### 5. Check it's running

```bash
sudo systemctl status blackhole-bot        # should show "active (running)"
sudo journalctl -u blackhole-bot -f        # live logs (Ctrl+C to exit)
```

### Useful commands

| Action | Command |
|---|---|
| Restart bot | `sudo systemctl restart blackhole-bot` |
| Stop bot | `sudo systemctl stop blackhole-bot` |
| View logs | `sudo journalctl -u blackhole-bot -f` |
| View last 100 lines | `sudo journalctl -u blackhole-bot -n 100` |

### Updating

```bash
cd /opt/blackhole-bot
git pull
sudo systemctl restart blackhole-bot
```

---

## Project structure

```
blackhole-bot/
├── main.py              # Bot entrypoint, keep-alive server, error handler
├── db.py                # SQLite helpers (forum_configs, notify_mentions, etc.)
├── requirements.txt     # py-cord + dependencies
├── .env.example         # Template for environment variables
├── deploy/
│   └── bot.service      # systemd unit file for Linux VPS
├── cogs/
│   ├── forum.py         # /forum help, /solve, /close, Create Help Post context menu
│   ├── settings.py      # /settings interactive panel (notifications, forums, permissions, mentions)
│   ├── permissions.py   # Per-command role overrides
│   └── watchers.py      # voices38 + Denuvo polling, /latest_cracks
└── data/                # SQLite database (auto-created, gitignored)
```

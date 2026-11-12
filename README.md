# Telegram File Sharing Bot

Pyrogram + MongoDB bot. Admins upload files → bot stores them in a private DB
channel → returns a deep link. Users open the link and receive the file(s),
with force-subscribe, auto-delete, content protection and anti-flood.

## Features
- Single-file links and `/batch` multi-file links
- Force-subscribe (multiple channels, Join + Try Again buttons)
- Auto-delete timer (persistent across restarts) + "get files again" button
- Protect content (no forwarding/saving)
- Admin: `/stats`, `/users`, `/broadcast`, `/ban`, `/unban`
- Anti-flood with temporary blocks, FloodWait handling, rotating logs

## Prerequisites
1. Create a bot with @BotFather → `BOT_TOKEN`.
2. Get `API_ID` / `API_HASH` from https://my.telegram.org.
3. Create a **private channel** (DB channel), add your bot as **admin** with "Post messages".
   Get its ID (starts with `-100`) by forwarding a channel message to @RawDataBot.
4. For force-sub, add the bot as admin in each required channel.
5. A MongoDB database (free MongoDB Atlas cluster is fine; allow your VPS IP).

## Configuration
Copy `.env.example` to `.env` and fill in the values. Never commit `.env`.

---

## A. Termux (Android): push the project to GitHub

```bash
pkg update && pkg upgrade -y
pkg install -y git openssh python
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
```

Create an **empty private repo** on github.com (e.g. `filesharebot`), then
choose ONE authentication method.

### Option 1: SSH key (recommended)
```bash
ssh-keygen -t ed25519 -C "you@example.com"      # press Enter for defaults
cat ~/.ssh/id_ed25519.pub                        # copy the output
```
GitHub → Settings → SSH and GPG keys → New SSH key → paste. Then:
```bash
ssh -T git@github.com                            # should greet you by username
cd ~/filesharebot
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin git@github.com:YOUR_USER/filesharebot.git
git push -u origin main
```

### Option 2: Personal access token (HTTPS)
GitHub → Settings → Developer settings → Personal access tokens → generate a
token with `repo` scope (fine-grained: Contents read/write on this repo).
```bash
cd ~/filesharebot
git init && git add . && git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USER/filesharebot.git
git config --global credential.helper store      # remember the token
git push -u origin main
# Username: YOUR_USER      Password: <paste the token>
```

Check `git status` first: `.env` must NOT appear (it is in `.gitignore`).

---

## B. VPS (Ubuntu 22.04)

Ubuntu 22.04 ships Python 3.10, so install 3.11 from the deadsnakes PPA.

```bash
sudo apt update && sudo apt install -y git software-properties-common build-essential
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

### Clone the repo
```bash
sudo mkdir -p /opt/filesharebot && sudo chown $USER:$USER /opt/filesharebot
# public repo / token:
git clone https://github.com/YOUR_USER/filesharebot.git /opt/filesharebot
# private repo via SSH deploy key (recommended):
#   ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""
#   cat ~/.ssh/deploy_key.pub   -> GitHub repo → Settings → Deploy keys → Add (read-only)
#   GIT_SSH_COMMAND="ssh -i ~/.ssh/deploy_key" git clone git@github.com:YOUR_USER/filesharebot.git /opt/filesharebot
cd /opt/filesharebot
```

### Option 1: systemd (venv)
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

cp .env.example .env
nano .env                                   # fill in your values

# edit User= and paths in bot.service if needed, then install it
sudo cp bot.service /etc/systemd/system/filesharebot.service
sudo systemctl daemon-reload
sudo systemctl enable --now filesharebot    # start now + on boot
```

Useful commands:
```bash
sudo systemctl status filesharebot          # state
sudo journalctl -u filesharebot -f          # live logs
tail -f /opt/filesharebot/logs/bot.log      # file log
sudo systemctl restart filesharebot
sudo systemctl stop filesharebot
```

### Option 2: Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

cp .env.example .env && nano .env
docker compose up -d --build                         # Atlas / external MongoDB
# or with bundled MongoDB (MONGO_URI=mongodb://mongo:27017):
# docker compose --profile local-db up -d --build

docker compose logs -f bot                           # logs
docker compose restart bot                           # restart
```

---

## C. Update workflow

1. **Termux:** edit code → `git add . && git commit -m "change" && git push`
2. **VPS:** `ssh user@your-vps-ip`
3. Update and restart:
   ```bash
   cd /opt/filesharebot && git pull
   # if requirements.txt changed:
   ./venv/bin/pip install -r requirements.txt
   sudo systemctl restart filesharebot
   ```
   Docker: `git pull && docker compose up -d --build`

## Usage
- **Admin:** send a file → get a link. `/batch` → send files → `/done` → one link.
- **Users:** open the link → join required channels (if any) → receive files.
- `/broadcast` must be sent **as a reply** to the message you want to broadcast.

## Troubleshooting

- **Invalid / revoked session** (`AUTH_KEY_UNREGISTERED`, `SESSION_REVOKED`, "database is locked"): stop the bot, delete `sessions/filesharebot.session*`, start again. "Database is locked" usually means two instances share one session, so check for a duplicate process or container. If you see `BadMsgNotification`, the server clock is off. Fix it with `sudo timedatectl set-ntp true`.
- **Channel not found** (`PeerIdInvalid`, `ChannelInvalid`, "Cannot access DB channel"): `DB_CHANNEL_ID` must include the `-100` prefix. Add the bot to the channel as admin first, then restart. If it still fails, post any message in the channel and restart.
- **Bot not admin in DB channel** (startup error "not an administrator", or `ChatAdminRequired` / `CHAT_WRITE_FORBIDDEN`): promote the bot and enable **Post messages**. The same applies to force-sub channels. A skipped channel is logged as an error and won't lock users out.
- **Mongo connection timeout** (`ServerSelectionTimeoutError`): on Atlas, add your VPS IP under Network Access and check the user and password in `MONGO_URI`.
- **TgCrypto fails to install**: run `sudo apt install build-essential python3.11-dev`. The bot also works without TgCrypto but is much slower.
- **`FloodWait` in logs**: the bot sleeps and retries automatically. If it happens constantly, lower the traffic or raise `FLOOD_*` limits.
- **"Link invalid / files no longer available"**: someone deleted the stored message from the DB channel. Never delete messages there manually.

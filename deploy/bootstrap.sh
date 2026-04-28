#!/bin/bash
# YOINTELL deployment bootstrap — Ubuntu 24.04 droplet
# Run as root on a freshly-created DigitalOcean droplet:
#   wget https://raw.githubusercontent.com/yogeshramm/NSE-Screener/main/deploy/bootstrap.sh
#   bash bootstrap.sh
#
# Prerequisites:
#   - Ubuntu 24.04 LTS x64 droplet
#   - Root SSH access
#   - Domain (moneystx.com) DNS pointing to this droplet's IP

set -e
set -u

DOMAIN="${DOMAIN:-moneystx.com}"
APP_USER="yointell"
APP_DIR="/home/${APP_USER}/NSE-Screener"
REPO_URL="git@github.com:yogeshramm/NSE-Screener.git"

echo "════════════════════════════════════════════════════════════"
echo "  YOINTELL Bootstrap → ${DOMAIN}"
echo "════════════════════════════════════════════════════════════"

# ── 1. SYSTEM UPDATE + ESSENTIAL PACKAGES ──────────────────────
echo ""
echo "[1/10] System update + base packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    python3.12 python3.12-venv python3-pip \
    git curl wget \
    ufw fail2ban \
    build-essential \
    cron \
    debian-keyring debian-archive-keyring apt-transport-https \
    unattended-upgrades

# ── 2. SWAP FILE (2GB RAM needs swap headroom) ─────────────────
echo "[2/10] Setting up 2GB swap file..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    sysctl vm.swappiness=10
fi

# ── 3. INSTALL CADDY (auto-HTTPS reverse proxy) ────────────────
echo "[3/10] Installing Caddy..."
if ! command -v caddy &>/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq caddy
fi

# ── 4. CREATE NON-ROOT USER ────────────────────────────────────
echo "[4/10] Creating user '${APP_USER}'..."
if ! id "${APP_USER}" &>/dev/null; then
    adduser --disabled-password --gecos "" "${APP_USER}"
    usermod -aG sudo "${APP_USER}"
fi

# Mirror root's authorized_keys so you can SSH in as yointell too
mkdir -p "/home/${APP_USER}/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
    cp /root/.ssh/authorized_keys "/home/${APP_USER}/.ssh/"
fi
chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.ssh"
chmod 700 "/home/${APP_USER}/.ssh"
[ -f "/home/${APP_USER}/.ssh/authorized_keys" ] && chmod 600 "/home/${APP_USER}/.ssh/authorized_keys"

# ── 5. GENERATE GITHUB DEPLOY KEY ──────────────────────────────
echo "[5/10] Generating GitHub deploy key..."
sudo -u "${APP_USER}" bash <<'EOSSH'
if [ ! -f ~/.ssh/id_ed25519 ]; then
    ssh-keygen -t ed25519 -C "moneystx-droplet" -f ~/.ssh/id_ed25519 -N ""
fi
ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null
EOSSH

PUBKEY=$(cat "/home/${APP_USER}/.ssh/id_ed25519.pub")

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ⚠️  ACTION REQUIRED: Add this as a GitHub deploy key"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  1. Open: https://github.com/yogeshramm/NSE-Screener/settings/keys"
echo "  2. Click 'Add deploy key'"
echo "  3. Title: moneystx-droplet"
echo "  4. Paste this key (read-only is fine):"
echo ""
echo "  ${PUBKEY}"
echo ""
echo "════════════════════════════════════════════════════════════"
read -p "Press ENTER once added on GitHub to continue..."

# ── 6. CLONE REPO ──────────────────────────────────────────────
echo "[6/10] Cloning YOINTELL repo..."
if [ ! -d "${APP_DIR}" ]; then
    sudo -u "${APP_USER}" git clone "${REPO_URL}" "${APP_DIR}"
else
    sudo -u "${APP_USER}" bash -c "cd ${APP_DIR} && git pull"
fi

# ── 7. PYTHON VENV + DEPS ──────────────────────────────────────
echo "[7/10] Setting up Python venv + installing dependencies..."
sudo -u "${APP_USER}" bash <<EOVENV
cd "${APP_DIR}"
if [ ! -d .venv ]; then
    python3.12 -m venv .venv
fi
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
EOVENV

# Create runtime dirs that aren't in git
sudo -u "${APP_USER}" mkdir -p \
    "${APP_DIR}/data_store/history" \
    "${APP_DIR}/data_store/fundamentals" \
    "${APP_DIR}/data_store/news" \
    "${APP_DIR}/data_store/institutional" \
    "${APP_DIR}/config/presets"

# Stub users.json if missing (you'll register your account via UI)
if [ ! -f "${APP_DIR}/config/users.json" ]; then
    sudo -u "${APP_USER}" bash -c "echo '{}' > ${APP_DIR}/config/users.json"
fi

# ── 8. SYSTEMD UNIT ────────────────────────────────────────────
echo "[8/10] Installing systemd unit..."
cp "${APP_DIR}/deploy/yointell.service" /etc/systemd/system/yointell.service
systemctl daemon-reload
systemctl enable yointell

# ── 9. CADDYFILE ───────────────────────────────────────────────
echo "[9/10] Configuring Caddy with ${DOMAIN}..."
sed "s/{{DOMAIN}}/${DOMAIN}/g" "${APP_DIR}/deploy/Caddyfile.template" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

# ── 10. FIREWALL + CRON + FAIL2BAN ─────────────────────────────
echo "[10/10] Firewall + cron + fail2ban..."

# Firewall
ufw --force reset > /dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Cron — daily 7am IST = 1:30am UTC
sudo -u "${APP_USER}" bash <<EOCRON
crontab -l 2>/dev/null | grep -v "daily_download.py" | { cat; echo "30 1 * * * cd ${APP_DIR} && .venv/bin/python daily_download.py >> data_store/cron.log 2>&1"; } | crontab -
EOCRON

# fail2ban — defaults protect SSH
systemctl enable --now fail2ban

# Auto security updates
echo 'APT::Periodic::Unattended-Upgrade "1";' > /etc/apt/apt.conf.d/20auto-upgrades
echo 'APT::Periodic::Update-Package-Lists "1";' >> /etc/apt/apt.conf.d/20auto-upgrades

# Start the app
systemctl start yointell

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ✅  BOOTSTRAP COMPLETE"
echo "════════════════════════════════════════════════════════════"
echo "  Status:    systemctl status yointell"
echo "  App logs:  journalctl -u yointell -f"
echo "  Caddy:     systemctl status caddy"
echo "  Visit:     https://${DOMAIN}"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  ⚠️  NEXT STEPS:"
echo "  1. In Cloudflare → ensure DNS A records exist (proxy can be ON)"
echo "  2. In Cloudflare → SSL/TLS → set mode to 'Full (strict)'"
echo "  3. Sync your historical data: from your LAPTOP run:"
echo "     rsync -avz ~/Documents/NSE-Screener/data_store/ \\"
echo "       ${APP_USER}@<droplet-ip>:${APP_DIR}/data_store/"
echo "  4. Sync config: rsync -avz ~/Documents/NSE-Screener/config/ \\"
echo "     ${APP_USER}@<droplet-ip>:${APP_DIR}/config/"
echo "  5. Restart: systemctl restart yointell"
echo "  6. Visit https://${DOMAIN} → register your account"
echo "════════════════════════════════════════════════════════════"

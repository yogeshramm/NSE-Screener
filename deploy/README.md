# YOINTELL Deployment Guide

Production deployment of YOINTELL on a DigitalOcean droplet at `https://moneystx.com`.

## Architecture

```
Cloudflare DNS + Proxy (free)
        │
        ▼
DigitalOcean Droplet (Bangalore, 2GB RAM, $14/mo)
├── Caddy (port 80/443, auto-HTTPS)
│       │
│       └── reverse_proxy → 127.0.0.1:8000
│
└── systemd: yointell.service
        └── uvicorn api.app:app (single worker)
                ├── data_store/history/*.pkl   (synced from laptop)
                ├── data_store/fundamentals/*  (auto-fetched)
                ├── config/users.json          (synced from laptop)
                └── cron: daily_download.py @ 7am IST
```

## Prerequisites

| | |
|---|---|
| Domain | `moneystx.com` registered at GoDaddy |
| DNS | Cloudflare (nameservers swapped at GoDaddy) |
| Server | DigitalOcean droplet, Ubuntu 24.04, BLR1 |
| Repo access | GitHub deploy key (added during bootstrap) |

## Order of operations

### Phase 1 — Account setup (only you can do this)

1. **Sign up DigitalOcean** → add payment method
2. **Sign up Cloudflare** (free)
3. **Cloudflare → Add Site `moneystx.com`** → copy 2 nameservers
4. **GoDaddy → Domain → Nameservers → Custom** → paste Cloudflare's 2 NS
5. Wait 5–30 min for nameserver propagation

### Phase 2 — Create droplet

1. **DO → Create → Droplets**
   - Region: **Bangalore (BLR1)**
   - OS: **Ubuntu 24.04 LTS x64**
   - Plan: **Basic → Premium AMD → 2GB / $14**
   - Auth: **SSH key** (paste your laptop's `~/.ssh/id_ed25519.pub`)
   - Hostname: `moneystx-prod`
   - Backups: ✅ enable
2. Wait ~60s → copy droplet IPv4

### Phase 3 — DNS records

In **Cloudflare → DNS → Records**:

```
Type=A   Name=@     Content=<droplet-IP>   Proxy=🟠 OFF (initially)
Type=A   Name=www   Content=<droplet-IP>   Proxy=🟠 OFF (initially)
```

⚠️ **Proxy must be OFF initially** so Let's Encrypt's HTTP-01 challenge can reach Caddy.
After Caddy obtains the cert (Phase 5), turn proxy ON.

### Phase 4 — Bootstrap droplet

```bash
# From your laptop
ssh root@<droplet-IP>

# On the droplet
wget https://raw.githubusercontent.com/yogeshramm/NSE-Screener/main/deploy/bootstrap.sh
bash bootstrap.sh
```

The script will:
1. Update Ubuntu, install Python 3.12, Caddy, ufw, fail2ban
2. Set up 2GB swap (essential at 2GB RAM)
3. Create `yointell` user (non-root)
4. Generate SSH deploy key → **pause and ask you to add it on GitHub**
5. Clone repo, install Python deps in venv
6. Install systemd unit + Caddyfile
7. Open firewall (22, 80, 443 only)
8. Add cron for daily 7am IST download
9. Enable auto security updates
10. Start the app

Total time: ~10 min (excluding the GitHub deploy key pause).

### Phase 5 — Sync your data (from laptop)

```bash
# On your LAPTOP (~30 min for 2 years × 2700 stocks)
rsync -avz --progress \
  ~/Documents/NSE-Screener/data_store/ \
  yointell@<droplet-IP>:/home/yointell/NSE-Screener/data_store/

# Auth + presets + watchlist
rsync -avz \
  ~/Documents/NSE-Screener/config/ \
  yointell@<droplet-IP>:/home/yointell/NSE-Screener/config/

# Restart server to pick up data
ssh root@<droplet-IP> 'systemctl restart yointell'
```

### Phase 6 — Turn on Cloudflare proxy

1. Cloudflare → DNS → Records → click both A records → toggle **Proxy ON** 🟠
2. Cloudflare → SSL/TLS → Overview → set mode to **Full (strict)**
3. Cloudflare → SSL/TLS → Edge Certificates → ✅ Always Use HTTPS

### Phase 7 — Verify

```bash
# DNS resolves
dig +short moneystx.com

# HTTPS works
curl -I https://moneystx.com
# Should see: HTTP/2 200, server: cloudflare (or Caddy if proxy off)

# App is up
ssh root@<droplet-IP> 'systemctl status yointell'
```

Visit https://moneystx.com → register your account → done.

## Operations

### View logs
```bash
ssh root@<droplet-IP>
journalctl -u yointell -f          # live app logs
journalctl -u caddy -f             # Caddy access/errors
tail -f /var/log/caddy/access.log  # JSON access log
tail -f /home/yointell/NSE-Screener/data_store/cron.log  # daily download
```

### Deploy updates
```bash
# After pushing to GitHub
ssh root@<droplet-IP>
sudo -u yointell bash -c 'cd /home/yointell/NSE-Screener && git pull && .venv/bin/pip install -r requirements.txt'
systemctl restart yointell
```

### Restart everything
```bash
systemctl restart yointell caddy
```

### Backup config (in addition to DO snapshots)
```bash
# From your laptop
rsync -avz yointell@<droplet-IP>:/home/yointell/NSE-Screener/config/ ~/yointell-backup/config/
```

## Cost summary

| Item | Monthly | Yearly |
|---|---|---|
| DO Droplet (2GB Premium AMD) | $14 (~₹1,170) | ₹14,000 |
| DO Backups (snapshots) | $2.40 (~₹200) | ₹2,400 |
| Domain (moneystx.com .com) | ~₹65 | ~₹780 |
| Cloudflare | Free | Free |
| **Total** | **~₹1,435/mo** | **~₹17,200/yr** |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `https://moneystx.com` shows Cloudflare 521 | Caddy not running OR proxy ON before cert issued | `systemctl status caddy`; turn CF proxy OFF until cert issued |
| Caddy logs "challenge failed" | Cloudflare proxy ON during issuance | Turn proxy OFF, `systemctl restart caddy`, wait 60s |
| 502 Bad Gateway | uvicorn down | `systemctl restart yointell`; check `journalctl -u yointell -n 50` |
| Daily download didn't run | Cron entry missing | `sudo -u yointell crontab -l` should show the entry |
| Out of memory crashes | Insufficient swap | Verify `/swapfile` mounted: `swapon --show` |

## Files in this folder

- `bootstrap.sh` — main install script
- `Caddyfile.template` — Caddy config (placeholders replaced at install)
- `yointell.service` — systemd unit
- `README.md` — this file

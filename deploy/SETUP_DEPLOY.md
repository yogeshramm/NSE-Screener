# GitHub Actions Deploy — One-Time Setup

This doc walks through converting the current rsync-based deploy to a GitHub
Actions auto-deploy. Run **once**. After setup, every `git push origin main`
triggers a tested deploy with auto-rollback on health check failure.

Workflow file: `.github/workflows/deploy.yml` (already committed).

---

## Prerequisites

- SSH access to the droplet (`ssh root@64.227.134.171`)
- Admin access to the GitHub repo (to add Deploy Key + Secrets)
- The droplet user `yointell` exists and the systemd service `yointell` is
  already running (it is — `systemctl status yointell`)

---

## Part A — On the droplet (run as `root`, or `yointell` with sudo)

### A1. Convert existing rsync target into a real git checkout

```bash
ssh root@64.227.134.171
sudo -u yointell -i   # become the yointell user

cd /home/yointell/NSE-Screener
git init -b main
git remote add origin git@github.com:yogeshramm/NSE-Screener.git
```

### A2. Generate a deploy key (SSH key the droplet uses to pull from GitHub)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/yointell_deploy -N "" -C "deploy@moneystx"

# Configure SSH to use this key only for github.com
cat >> ~/.ssh/config <<'EOF'
Host github-deploy
  HostName github.com
  User git
  IdentityFile ~/.ssh/yointell_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

# Point our git remote at the keyed alias
git remote set-url origin git@github-deploy:yogeshramm/NSE-Screener.git

# Print the PUBLIC key — copy this whole line for step A3
cat ~/.ssh/yointell_deploy.pub
```

### A3. Add deploy key to GitHub

1. Go to: <https://github.com/yogeshramm/NSE-Screener/settings/keys>
2. Click **Add deploy key**
3. Title: `yointell-droplet`
4. Key: paste the line from A2 (`ssh-ed25519 AAAA…`)
5. **Leave "Allow write access" UNCHECKED** (read-only is enough)
6. Click **Add key**

### A4. First fetch (still as `yointell` on the droplet)

```bash
# This may complain about untracked files (data_store/, config/) — that's fine, they're gitignored
ssh -T -o StrictHostKeyChecking=accept-new git@github-deploy   # accepts host key once

git fetch origin main
git reset --hard origin/main
git status
# expect: "On branch main · nothing to commit, working tree clean"
```

### A5. Configure passwordless sudo for service restart

The Actions deploy needs `sudo systemctl restart yointell` without a password.

```bash
exit   # back to root

echo "yointell ALL=(ALL) NOPASSWD: /bin/systemctl restart yointell" | sudo tee /etc/sudoers.d/yointell-deploy
sudo chmod 440 /etc/sudoers.d/yointell-deploy
sudo visudo -c   # validates syntax — must say "/etc/sudoers: parsed OK"

# Test as yointell
sudo -u yointell sudo systemctl restart yointell
sudo systemctl status yointell --no-pager | head -10
```

### A6. Generate the SSH key GitHub Actions will use to log in

This is a **separate** key from the deploy key in A2. The deploy key authenticates
droplet→GitHub. This new key authenticates GitHub Actions→droplet.

```bash
# On the droplet, as root
ssh-keygen -t ed25519 -f /tmp/actions_to_droplet -N "" -C "actions@yointell"

# Authorise the public key for the yointell user
mkdir -p /home/yointell/.ssh
cat /tmp/actions_to_droplet.pub >> /home/yointell/.ssh/authorized_keys
chmod 700 /home/yointell/.ssh
chmod 600 /home/yointell/.ssh/authorized_keys
chown -R yointell:yointell /home/yointell/.ssh

# Print the PRIVATE key — copy ALL lines including BEGIN and END for Part B
cat /tmp/actions_to_droplet

# Then DELETE the temp files (the GitHub Secret is now the only copy)
shred -u /tmp/actions_to_droplet /tmp/actions_to_droplet.pub
```

### A7. Test the SSH login from your Mac (sanity check)

```bash
# On your Mac — paste the private key into a temp file
pbpaste > /tmp/test_key   # if you copied it; otherwise nano it
chmod 600 /tmp/test_key

ssh -i /tmp/test_key yointell@64.227.134.171 "whoami && hostname"
# expect: yointell  yointell-droplet
rm /tmp/test_key
```

If that works, GitHub Actions will work too.

---

## Part B — On GitHub (web UI)

### B1. Add Action secrets

Go to: <https://github.com/yogeshramm/NSE-Screener/settings/secrets/actions>

Click **New repository secret** for each:

| Name           | Value                                                          |
|----------------|----------------------------------------------------------------|
| `PROD_HOST`    | `64.227.134.171`                                               |
| `PROD_USER`    | `yointell`                                                     |
| `PROD_SSH_KEY` | the **full private key** from step A6 (BEGIN…END, all lines)   |
| `PROD_SSH_PORT`| (optional) `22` — only set if your SSH port is non-standard    |

---

## Part C — First deploy

```bash
# On your Mac
cd ~/Documents/NSE-Screener
git checkout main
git pull   # in case there are commits we don't have locally
git push origin main
```

Then watch:

<https://github.com/yogeshramm/NSE-Screener/actions>

You should see "Deploy to production" running. It logs:

```
→ before: <short-sha>
→ after:  <short-sha>
→ service restarted
✓ health check passed (attempt 1)
```

Verify production:

```bash
curl -s https://moneystx.com/data/status | head -1
```

---

## Rollback procedure (if something breaks AFTER auto-rollback also fails)

```bash
ssh root@64.227.134.171
sudo -u yointell -i
cd /home/yointell/NSE-Screener

git log --oneline -10                # find a known-good SHA
git reset --hard <sha>
exit
sudo systemctl restart yointell
curl -fsS http://localhost:8000/data/status   # confirm
```

---

## What about the existing rsync workflow?

Stop using it. From now on:
- Edit code locally → `git commit` → `git push origin main` → done.
- No more manual rsync. No more drift.
- `git log` on the droplet shows exactly what's running.

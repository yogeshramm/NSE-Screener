#!/usr/bin/env bash
# pull_analyst_cache.sh — downloads latest analyst JSON files from GitHub
# Runs daily at 17:00 IST (11:30 UTC) — ~30 min after GHA workflow commits.
# No git needed; uses GitHub raw content API (public repo).

REPO="yogeshramm/NSE-Screener"
BRANCH="main"
DIR="/home/yointell/NSE-Screener/data_store/analyst"
API="https://api.github.com/repos/${REPO}/contents/data_store/analyst?ref=${BRANCH}"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}/data_store/analyst"

mkdir -p "$DIR"

# Get list of JSON files in analyst directory from GitHub API
FILES=$(curl -sf "$API" | python3 -c "
import sys, json
items = json.load(sys.stdin)
for item in items:
    if item.get('name','').endswith('.json'):
        print(item['name'])
" 2>/dev/null)

if [ -z "$FILES" ]; then
    echo "[pull_analyst_cache] Could not list files from GitHub API" >&2
    exit 1
fi

ok=0; skip=0; fail=0
for fname in $FILES; do
    dest="$DIR/$fname"
    # Check remote last-modified via HEAD (saves bandwidth when unchanged)
    remote_etag=$(curl -sf -I "${RAW}/${fname}" | grep -i '^etag:' | tr -d '\r' | awk '{print $2}')
    local_etag=""
    if [ -f "$dest.etag" ]; then
        local_etag=$(cat "$dest.etag")
    fi
    if [ -n "$remote_etag" ] && [ "$remote_etag" = "$local_etag" ]; then
        skip=$((skip+1))
        continue
    fi
    if curl -sf "${RAW}/${fname}" -o "$dest.tmp"; then
        mv "$dest.tmp" "$dest"
        echo "$remote_etag" > "$dest.etag"
        ok=$((ok+1))
    else
        fail=$((fail+1))
    fi
done

echo "[pull_analyst_cache] Done: ${ok} updated, ${skip} unchanged, ${fail} failed"

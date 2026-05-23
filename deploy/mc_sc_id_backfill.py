"""
MC SC_ID Backfill — one-time cron job that runs every 3 hours.

Processes up to BATCH_SIZE unmatched NSE stocks per run.
Priority: Nifty50 → Nifty100 → Nifty200 → Nifty500 → all NSE.
Exits 0 in all cases; cron stops calling when queue is empty
(detected by "DONE — nothing left to process" in stdout).

Tracks failed attempts in data/mc_sc_ids_unavailable.json.
After MAX_RETRIES failures a stock is skipped permanently.

Run:
    python deploy/mc_sc_id_backfill.py [--batch N] [--dry-run]
Cron (every 3 hours):
    0 */3 * * * cd /home/yointell/NSE-Screener && python deploy/mc_sc_id_backfill.py >> logs/mc_sc_id_backfill.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import curl_cffi.requests as cf_requests
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

BATCH_SIZE = 300
MAX_RETRIES = 3
SLEEP_BETWEEN = 0.4  # seconds between MC requests

SESSION = cf_requests.Session(impersonate="chrome124")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moneycontrol.com/",
}

# All MC index pages known to render stock rows server-side.
# The smallcap-100 page renders ~1100 stocks across all categories.
MC_INDEX_PAGES = [
    ("Nifty 50",          "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-50-stocks/9"),
    ("Nifty Next 50",     "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-next-50-stocks/14"),
    ("Nifty 100",         "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-100-stocks/25"),
    ("Nifty 200",         "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-200-stocks/50"),
    ("Nifty 500",         "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-500-stocks/115"),
    ("Nifty Midcap 100",  "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-midcap-100-stocks/46"),
    ("Nifty Midcap 150",  "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-midcap-150-stocks/76"),
    ("Nifty Smallcap 100","https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-smallcap-100-stocks/89"),
    ("Nifty Smallcap 250","https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-smallcap-250-stocks/103"),
    ("Nifty Microcap 250","https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-microcap-250-stocks/128"),
    ("Nifty Bank",        "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-bank-stocks/35"),
    ("Nifty IT",          "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-it-stocks/36"),
    ("Nifty Pharma",      "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-pharma-stocks/73"),
    ("Nifty FMCG",        "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-fmcg-stocks/37"),
    ("Nifty Auto",        "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-auto-stocks/41"),
    ("Nifty Metal",       "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-metal-stocks/40"),
    ("Nifty Energy",      "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-energy-stocks/38"),
    ("Nifty Realty",      "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-realty-stocks/74"),
    ("Nifty Finance",     "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-financial-services-stocks/56"),
    ("Nifty Private Bank","https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-private-bank-stocks/59"),
    ("Nifty PSU Bank",    "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-psu-bank-stocks/53"),
    ("Nifty Infra",       "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-infrastructure-stocks/60"),
    ("Nifty Chemicals",   "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-chemicals-stocks/71"),
    ("Nifty Healthcare",  "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-healthcare-stocks/101"),
    ("Nifty Media",       "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-media-stocks/39"),
    ("Nifty MNC",         "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-mnc-stocks/64"),
    ("Nifty CPSE",        "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-cpse-stocks/130"),
    ("BSE 500",           "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-500-stocks/11"),
    ("BSE Midcap",        "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-midcap-stocks/6"),
    ("BSE Smallcap",      "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-smallcap-stocks/7"),
    ("BSE 200",           "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-200-stocks/4"),
    ("BSE LargeMidCap",   "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-largemidcap-stocks/20"),
]

SC_ID_RE = re.compile(
    r'href="https://www\.moneycontrol\.com/india/stockpricequote/[^/]+/([^/]+)/([A-Z][A-Z0-9]{0,6})"[^>]*>([^<]{3,60})<'
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def build_slug_map() -> tuple[dict, dict]:
    """Scrape all MC index pages and return (slug→scid, norm_name→(scid,slug,mc_name))."""
    slug_to_scid: dict[str, str] = {}
    name_to_scid: dict[str, tuple] = {}
    total = 0
    for label, url in MC_INDEX_PAGES:
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=15)
            rows = SC_ID_RE.findall(r.text)
            for slug, scid, mc_name in rows:
                slug_to_scid[slug] = scid
                norm = _norm(mc_name)
                name_to_scid[norm] = (scid, slug, mc_name.strip())
            total += len(rows)
            time.sleep(SLEEP_BETWEEN)
        except Exception as e:
            print(f"  [warn] {label}: {e}")
    print(f"  Slug map: {len(slug_to_scid)} entries from {len(MC_INDEX_PAGES)} pages ({total} raw rows)")
    return slug_to_scid, name_to_scid


def match_symbol(
    sym: str,
    company_name: str,
    slug_to_scid: dict,
    name_to_scid: dict,
) -> str | None:
    """Try to find SC_ID for `sym` using company name against MC slug/name map."""
    norm_name = _norm(company_name)

    # Exact normalized name match
    if norm_name in name_to_scid:
        scid, slug, mc_name = name_to_scid[norm_name]
        return scid

    # Symbol itself as slug (many stocks match directly)
    sym_lower = sym.lower().replace("&", "").replace("-", "")
    if sym_lower in slug_to_scid:
        return slug_to_scid[sym_lower]

    # Prefix match on first 8 chars of normalized name vs slug
    prefix = norm_name[:10]
    candidates = [(s, v) for s, v in slug_to_scid.items() if s.startswith(prefix) or prefix.startswith(s[:8])]
    if len(candidates) == 1:
        return candidates[0][1]
    if len(candidates) > 1:
        # Shortest slug = most direct match
        return min(candidates, key=lambda x: len(x[0]))[1]

    # Substring: name starts with slug key (first 6 chars)
    sub_candidates = [(s, v) for s, v in slug_to_scid.items() if norm_name.startswith(s[:6]) and len(s) >= 6]
    if len(sub_candidates) == 1:
        return sub_candidates[0][1]

    return None


def load_priority_queue(sc_id_map: dict, unavailable: dict) -> list[tuple[str, int]]:
    """
    Return list of (symbol, priority) for all unprocessed NSE equity stocks.
    Priority 1=Nifty50, 2=Nifty100, 3=Nifty200, 4=Nifty500, 5=others.
    Already mapped or max-retried symbols are excluded.
    """
    # Load index membership sets
    def fetch_index_syms(url: str) -> set[str]:
        try:
            df = pd.read_csv(url)
            df.columns = [c.strip() for c in df.columns]
            col = next((c for c in df.columns if "symbol" in c.lower()), None)
            if col:
                return set(df[col].str.strip().tolist())
        except Exception:
            pass
        return set()

    nifty50 = fetch_index_syms(
        "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
    )
    nifty100 = fetch_index_syms(
        "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"
    )
    nifty200 = fetch_index_syms(
        "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    )
    nifty500 = fetch_index_syms(
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    )

    # Fall back to local file for Nifty500 if NSE unreachable
    local_n500 = DATA / "nifty500_live.txt"
    if not nifty500 and local_n500.exists():
        nifty500 = set(local_n500.read_text().split())

    # All NSE equity symbols
    try:
        df_all = pd.read_csv("https://archives.nseindia.com/content/equities/EQUITY_L.csv")
        df_all.columns = [c.strip() for c in df_all.columns]
        df_all["SYMBOL"] = df_all["SYMBOL"].str.strip()
        all_syms = set(df_all["SYMBOL"].tolist())
    except Exception as e:
        print(f"  [warn] NSE equity list failed: {e}")
        all_syms = nifty500.copy()

    # Assign priority
    queue: list[tuple[str, int]] = []
    seen = set(sc_id_map.keys())

    for sym in all_syms:
        if sym in seen:
            continue
        retries = unavailable.get(sym, {}).get("attempts", 0)
        if retries >= MAX_RETRIES:
            continue
        if sym in nifty50:
            pri = 1
        elif sym in nifty100:
            pri = 2
        elif sym in nifty200:
            pri = 3
        elif sym in nifty500:
            pri = 4
        else:
            pri = 5
        queue.append((sym, pri))

    queue.sort(key=lambda x: x[1])
    return queue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today = date.today().isoformat()
    print(f"[mc_backfill] {today} starting (batch={args.batch})", flush=True)

    # Load current map
    map_path = DATA / "mc_sc_ids.json"
    unav_path = DATA / "mc_sc_ids_unavailable.json"

    sc_id_map: dict = json.loads(map_path.read_text()) if map_path.exists() else {}
    unavailable: dict = json.loads(unav_path.read_text()) if unav_path.exists() else {}

    # Build priority queue
    print("  Building priority queue...", flush=True)
    queue = load_priority_queue(sc_id_map, unavailable)

    if not queue:
        print("DONE — nothing left to process", flush=True)
        return 0

    batch = queue[: args.batch]
    print(f"  Queue: {len(queue)} remaining | processing {len(batch)} this run", flush=True)
    print(f"  Priority breakdown: " + ", ".join(
        f"p{p}={sum(1 for _, x in queue if x==p)}" for p in [1,2,3,4,5]
    ), flush=True)

    # Load company names from NSE
    sym_to_name: dict[str, str] = {}
    try:
        df_eq = pd.read_csv("https://archives.nseindia.com/content/equities/EQUITY_L.csv")
        df_eq.columns = [c.strip() for c in df_eq.columns]
        df_eq["SYMBOL"] = df_eq["SYMBOL"].str.strip()
        sym_to_name = dict(zip(df_eq["SYMBOL"], df_eq["NAME OF COMPANY"].str.strip()))
    except Exception as e:
        print(f"  [warn] NSE company names: {e}", flush=True)

    # Build slug→SC_ID map from MC index pages
    print("  Scraping MC index pages...", flush=True)
    slug_to_scid, name_to_scid = build_slug_map()

    # Reverse map: scid → sym for collision detection
    used_scids: set[str] = set(sc_id_map.values())

    # Match batch
    found = 0
    not_found = 0

    for sym, pri in batch:
        company_name = sym_to_name.get(sym, "")
        if not company_name:
            # No name → mark unavailable
            unavailable.setdefault(sym, {"attempts": 0, "reason": "no_nse_name", "last_tried": today})
            unavailable[sym]["attempts"] += 1
            unavailable[sym]["last_tried"] = today
            not_found += 1
            continue

        short = (
            company_name.replace(" Limited", "")
            .replace(" Ltd.", "")
            .replace(" Ltd", "")
            .strip()
        )
        sc_id = match_symbol(sym, short, slug_to_scid, name_to_scid)
        if not sc_id:
            sc_id = match_symbol(sym, company_name, slug_to_scid, name_to_scid)

        if sc_id:
            if sc_id in used_scids:
                # SC_ID already claimed by a different symbol — skip to avoid collision
                print(f"  [{pri}] {sym:15s} → {sc_id} COLLISION (already used), skipping", flush=True)
                entry = unavailable.setdefault(sym, {"attempts": 0, "reason": "collision", "last_tried": today})
                entry["attempts"] += 1
                entry["last_tried"] = today
                not_found += 1
            else:
                sc_id_map[sym] = sc_id
                used_scids.add(sc_id)
                print(f"  [{pri}] {sym:15s} → {sc_id}", flush=True)
                found += 1
        else:
            entry = unavailable.setdefault(sym, {"attempts": 0, "reason": "not_found", "last_tried": today})
            entry["attempts"] += 1
            entry["last_tried"] = today
            print(f"  [{pri}] {sym:15s} → NOT FOUND (attempt {entry['attempts']}/{MAX_RETRIES})", flush=True)
            not_found += 1

    print(f"\n  Found: {found}, Not found: {not_found}", flush=True)
    print(f"  Total mapped: {len(sc_id_map)}", flush=True)

    if not args.dry_run:
        map_path.write_text(json.dumps(sc_id_map, indent=2, sort_keys=True))
        unav_path.write_text(json.dumps(unavailable, indent=2, sort_keys=True))
        print(f"  Saved → {map_path.name} ({len(sc_id_map)} entries)", flush=True)
    else:
        print("  [dry-run] no files written", flush=True)

    # Check if queue is now empty
    remaining = len(queue) - len(batch)
    permanently_skipped = sum(1 for v in unavailable.values() if v.get("attempts", 0) >= MAX_RETRIES)
    print(f"  ~{remaining} symbols remaining after this run ({permanently_skipped} permanently skipped)", flush=True)

    if remaining <= 0:
        print("DONE — nothing left to process", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())

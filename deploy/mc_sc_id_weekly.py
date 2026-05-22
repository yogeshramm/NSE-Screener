"""
MC SC_ID Weekly Refresh — runs every Saturday.

1. Downloads fresh NSE equity list.
2. Finds symbols not yet in mc_sc_ids.json (newly listed stocks).
3. Matches them against MC using the same index-page scraping approach.
4. Also resets retry count for stocks that had transient failures > 30 days ago.

Priority within new stocks: Nifty50 → Nifty100 → Nifty200 → Nifty500 → others.

Run:
    python deploy/mc_sc_id_weekly.py [--dry-run]
Cron (Saturday 9:00 AM IST = 3:30 UTC):
    30 3 * * 6  cd /home/yointell/NSE-Screener && python deploy/mc_sc_id_weekly.py >> logs/mc_sc_id_weekly.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import curl_cffi.requests as cf_requests
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

MAX_RETRIES = 3
RETRY_RESET_DAYS = 30   # re-try stocks that failed > 30 days ago (MC may have added page)
SLEEP_BETWEEN = 0.4

SESSION = cf_requests.Session(impersonate="chrome124")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moneycontrol.com/",
}

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
    ("Nifty Chemicals",   "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-chemicals-stocks/71"),
    ("Nifty Healthcare",  "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-healthcare-stocks/101"),
    ("Nifty MNC",         "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-mnc-stocks/64"),
    ("Nifty CPSE",        "https://www.moneycontrol.com/markets/indian-indices/top-nse-india-nifty-cpse-stocks/130"),
    ("BSE 500",           "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-500-stocks/11"),
    ("BSE Midcap",        "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-midcap-stocks/6"),
    ("BSE Smallcap",      "https://www.moneycontrol.com/markets/indian-indices/top-bse-bse-smallcap-stocks/7"),
]

SC_ID_RE = re.compile(
    r'href="https://www\.moneycontrol\.com/india/stockpricequote/[^/]+/([^/]+)/([A-Z][A-Z0-9]{0,6})"[^>]*>([^<]{3,60})<'
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def build_slug_map() -> tuple[dict, dict]:
    slug_to_scid: dict[str, str] = {}
    name_to_scid: dict[str, tuple] = {}
    for label, url in MC_INDEX_PAGES:
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=15)
            for slug, scid, mc_name in SC_ID_RE.findall(r.text):
                slug_to_scid[slug] = scid
                name_to_scid[_norm(mc_name)] = (scid, slug, mc_name.strip())
            time.sleep(SLEEP_BETWEEN)
        except Exception as e:
            print(f"  [warn] {label}: {e}")
    print(f"  Slug map: {len(slug_to_scid)} entries")
    return slug_to_scid, name_to_scid


def match_symbol(sym: str, company_name: str, slug_to_scid: dict, name_to_scid: dict) -> str | None:
    norm_name = _norm(company_name)

    if norm_name in name_to_scid:
        return name_to_scid[norm_name][0]

    sym_lower = sym.lower().replace("&", "").replace("-", "")
    if sym_lower in slug_to_scid:
        return slug_to_scid[sym_lower]

    prefix = norm_name[:10]
    candidates = [(s, v) for s, v in slug_to_scid.items() if s.startswith(prefix) or prefix.startswith(s[:8])]
    if len(candidates) == 1:
        return candidates[0][1]
    if len(candidates) > 1:
        return min(candidates, key=lambda x: len(x[0]))[1]

    sub_candidates = [(s, v) for s, v in slug_to_scid.items() if norm_name.startswith(s[:6]) and len(s) >= 6]
    if len(sub_candidates) == 1:
        return sub_candidates[0][1]

    return None


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


def priority_of(sym: str, n50: set, n100: set, n200: set, n500: set) -> int:
    if sym in n50:
        return 1
    if sym in n100:
        return 2
    if sym in n200:
        return 3
    if sym in n500:
        return 4
    return 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today = date.today().isoformat()
    print(f"[mc_weekly] {today} starting", flush=True)

    map_path = DATA / "mc_sc_ids.json"
    unav_path = DATA / "mc_sc_ids_unavailable.json"

    sc_id_map: dict = json.loads(map_path.read_text()) if map_path.exists() else {}
    unavailable: dict = json.loads(unav_path.read_text()) if unav_path.exists() else {}

    # Reset retry count for old failures — MC may have added the page since
    cutoff = (datetime.now() - timedelta(days=RETRY_RESET_DAYS)).date().isoformat()
    reset_count = 0
    for sym, entry in list(unavailable.items()):
        if entry.get("attempts", 0) >= MAX_RETRIES and entry.get("last_tried", "9999") < cutoff:
            entry["attempts"] = 0
            reset_count += 1
    if reset_count:
        print(f"  Reset retry count for {reset_count} stocks (last tried > {RETRY_RESET_DAYS}d ago)", flush=True)

    # Load full NSE equity list
    try:
        df_eq = pd.read_csv("https://archives.nseindia.com/content/equities/EQUITY_L.csv")
        df_eq.columns = [c.strip() for c in df_eq.columns]
        df_eq["SYMBOL"] = df_eq["SYMBOL"].str.strip()
        sym_to_name = dict(zip(df_eq["SYMBOL"], df_eq["NAME OF COMPANY"].str.strip()))
        all_syms = set(df_eq["SYMBOL"].tolist())
        print(f"  NSE equity list: {len(all_syms)} symbols", flush=True)
    except Exception as e:
        print(f"  [error] NSE equity list failed: {e}", flush=True)
        return 1

    # Identify new and retry-eligible symbols
    nifty50  = fetch_index_syms("https://archives.nseindia.com/content/indices/ind_nifty50list.csv")
    nifty100 = fetch_index_syms("https://archives.nseindia.com/content/indices/ind_nifty100list.csv")
    nifty200 = fetch_index_syms("https://archives.nseindia.com/content/indices/ind_nifty200list.csv")
    nifty500 = fetch_index_syms("https://archives.nseindia.com/content/indices/ind_nifty500list.csv")

    # Fall back to local list if NSE unreachable
    local_n500 = DATA / "nifty500_live.txt"
    if not nifty500 and local_n500.exists():
        nifty500 = set(local_n500.read_text().split())

    to_process: list[tuple[str, int]] = []
    new_count = 0
    retry_count = 0

    for sym in all_syms:
        if sym in sc_id_map:
            continue
        retries = unavailable.get(sym, {}).get("attempts", 0)
        if retries >= MAX_RETRIES:
            continue
        pri = priority_of(sym, nifty50, nifty100, nifty200, nifty500)
        is_new = sym not in unavailable
        if is_new:
            new_count += 1
        else:
            retry_count += 1
        to_process.append((sym, pri))

    to_process.sort(key=lambda x: x[1])

    print(f"  To process: {len(to_process)} ({new_count} new listings, {retry_count} retries)", flush=True)
    if not to_process:
        print("  Nothing new to do.", flush=True)
        return 0

    # Build slug map
    print("  Scraping MC index pages...", flush=True)
    slug_to_scid, name_to_scid = build_slug_map()

    used_scids: set[str] = set(sc_id_map.values())

    found = 0
    not_found = 0

    for sym, pri in to_process:
        company_name = sym_to_name.get(sym, "")
        if not company_name:
            unavailable.setdefault(sym, {"attempts": 0, "reason": "no_nse_name", "last_tried": today})
            unavailable[sym]["attempts"] += 1
            unavailable[sym]["last_tried"] = today
            not_found += 1
            continue

        short = company_name.replace(" Limited", "").replace(" Ltd.", "").replace(" Ltd", "").strip()
        sc_id = match_symbol(sym, short, slug_to_scid, name_to_scid)
        if not sc_id:
            sc_id = match_symbol(sym, company_name, slug_to_scid, name_to_scid)

        if sc_id:
            if sc_id in used_scids:
                print(f"  [{pri}] {sym:15s} → {sc_id} COLLISION (already used), skipping", flush=True)
                entry = unavailable.setdefault(sym, {"attempts": 0, "reason": "collision", "last_tried": today})
                entry["attempts"] += 1
                entry["last_tried"] = today
                not_found += 1
            else:
                sc_id_map[sym] = sc_id
                used_scids.add(sc_id)
                unavailable.pop(sym, None)
                print(f"  [{pri}] {sym:15s} → {sc_id}", flush=True)
                found += 1
        else:
            entry = unavailable.setdefault(sym, {"attempts": 0, "reason": "not_found", "last_tried": today})
            entry["attempts"] += 1
            entry["last_tried"] = today
            not_found += 1

    print(f"\n  Results: {found} found, {not_found} not found", flush=True)
    print(f"  Total mapped: {len(sc_id_map)}", flush=True)

    if not args.dry_run:
        map_path.write_text(json.dumps(sc_id_map, indent=2, sort_keys=True))
        unav_path.write_text(json.dumps(unavailable, indent=2, sort_keys=True))
        print(f"  Saved → {map_path.name} ({len(sc_id_map)} entries)", flush=True)
    else:
        print("  [dry-run] no files written", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())

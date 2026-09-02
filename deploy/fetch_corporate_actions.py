#!/usr/bin/env python3
"""Fetch splits and bonuses per symbol from NSE's corporate-actions endpoint.

Same official source `data/nse_events.py` already uses for dividends —
/api/corporates-corporateActions — but here we keep the SPLIT and BONUS
records and turn each into a price-adjustment factor.

The factor is derived from NSE's own announcement text, never inferred from a
price gap. Anything the parser cannot read confidently is recorded as
`unparsed` and reported, not guessed at.

    BONUS 1:2        1 free share for every 2 held  -> 3 shares per 2  -> f = 2/3
    BONUS 1:1        1 for 1                        -> 2 per 1         -> f = 1/2
    SPLIT 10 -> 2    face value 10 becomes 2        -> 5 shares per 1  -> f = 1/5

A bar BEFORE the ex-date is multiplied by the cumulative factor of every
action on or after it, which puts the whole series on today's share basis.

    python3 deploy/fetch_corporate_actions.py --symbols TCS,RELIANCE
    python3 deploy/fetch_corporate_actions.py            # every stored symbol

Output: data_store/corporate_actions/{SYMBOL}.json
Resumable: an existing file is skipped unless --force.
READ-ONLY with respect to price data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HIST = os.path.join(ROOT, "data_store", "history")
OUT = os.path.join(ROOT, "data_store", "corporate_actions")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
    "X-Requested-With": "XMLHttpRequest",
}


def log(m):
    print(f"{datetime.now():%H:%M:%S}  {m}", flush=True)


def session():
    try:
        from curl_cffi import requests as cf
        s = cf.Session(impersonate="chrome131")
    except Exception:
        import requests
        s = requests.Session()
    s.headers.update(HEADERS)
    for u in ("https://www.nseindia.com",
              "https://www.nseindia.com/companies-listing/corporate-filings-actions"):
        try:
            s.get(u, timeout=10)
        except Exception:
            pass
    return s


def parse_factor(subject: str):
    """Return (factor, kind, detail) or (None, kind, why) if unreadable.

    factor multiplies PRE-ex-date prices to put them on the post-action basis.

    Two traps NSE's text sets, both found by the adjustment verifier:

      compound subjects  "Bonus 1:1/Face Value Split - From Rs 10 To Rs 2" is
                         TWO actions on one line. Matching only the first
                         under-adjusts by the second (BAJFINANCE 2016-09-08:
                         real factor 0.1, first-match gives 0.5).

      non-equity bonus   "Bonus Ncrps 4:1" issues preference shares, which do
                         not touch the equity price at all (TVSMOTOR
                         2025-08-25: price did not move; applying 0.2 was
                         a pure fabrication).
    """
    t = " ".join(subject.split()).upper()

    # A bonus of anything other than equity does not adjust the share price.
    if "BONUS" in t and re.search(r"\bNCRPS\b|\bNCD\b|PREFERENCE|DEBENTURE", t):
        return None, "non_equity_bonus", "bonus of preference shares/debentures — price unaffected"

    # ---- BONUS and SPLIT — a subject may carry BOTH; combine them ----
    combined = 1.0
    bits = []
    m = re.search(r"BONUS[^0-9]{0,20}(\d+)\s*[:/]\s*(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            combined *= b / (a + b)
            bits.append(f"bonus {a}:{b}")
        else:
            return None, "bonus", f"bad ratio {a}:{b}"

    m = re.search(r"(?:SPLIT|SUB[- ]?DIVISION|SUBDIVISION)[^0-9]{0,40}?"
                  r"(?:RS\.?\s*)?(\d+(?:\.\d+)?)[^0-9]{1,20}?(?:RS\.?\s*)?(\d+(?:\.\d+)?)", t)
    if m and ("SPLIT" in t or "DIVISION" in t):
        frm, to = float(m.group(1)), float(m.group(2))
        if frm > 0 and to > 0 and to < frm:
            combined *= to / frm
            bits.append(f"split FV {frm:g}->{to:g}")
        elif not bits:
            return None, "split", f"unreadable FV {frm:g}->{to:g}"

    if bits:
        kind = "bonus+split" if len(bits) > 1 else ("bonus" if "bonus" in bits[0] else "split")
        return combined, kind, " + ".join(bits)

    # ---- RIGHTS a:b at a stated price ----
    # factor needs the cum-date market price, so it is derived later; the
    # announcement gives us the ratio and the subscription price.
    m = re.search(r"RIGHTS[^0-9]{0,20}(\d+)\s*[:/]\s*(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        pm = re.search(r"(?:PREMIUM\s*)?RS\.?\s*(\d+(?:\.\d+)?)", t)
        price = float(pm.group(1)) if pm else None
        prem = "PREMIUM" in t
        return None, "rights", f"{a}:{b}" + (f" @{'prem ' if prem else ''}{price:g}" if price else "")

    # ---- Demerger / scheme of arrangement ----
    # NSE publishes the event and ex-date but never a value split, so the
    # factor is measured from the price at that known ex-date (see
    # deploy/derive_action_factors.py). We never infer the EVENT from price.
    if "DEMERG" in t or "ARRANGEMENT" in t:
        return None, "demerger", "ratio not published by NSE — derive from ex-date"

    # ---- things that do NOT adjust the price series ----
    if "BUY BACK" in t or "BUYBACK" in t:
        return None, "buyback", "no price adjustment"
    if "MEETING" in t or "AGM" in t or "EGM" in t:
        return None, "meeting", "no price adjustment"

    if "BONUS" in t:
        return None, "bonus", "ratio not found"
    if "SPLIT" in t or "DIVISION" in t:
        return None, "split", "face values not found"
    return None, "other", "not a price-adjusting action"


def fetch_symbol(sess, sym: str, years: int = 12):
    from datetime import timedelta
    today = datetime.utcnow()
    frm = (today - timedelta(days=years * 365)).strftime("%d-%m-%Y")
    to = today.strftime("%d-%m-%Y")
    url = ("https://www.nseindia.com/api/corporates-corporateActions"
           f"?index=equities&from_date={frm}&to_date={to}&symbol={sym}")
    r = sess.get(url, timeout=20)
    if not getattr(r, "ok", False):
        return None
    raw = r.json()
    items = raw if isinstance(raw, list) else raw.get("data", [])

    actions, unparsed = [], []
    for it in items or []:
        subj = (it.get("subject") or "").strip()
        ex = (it.get("exDate") or "").strip()
        if not subj or not ex or ex == "-":
            continue
        f, kind, detail = parse_factor(subj)
        if kind in ("other", "buyback", "meeting", "non_equity_bonus"):
            continue          # these do not adjust the price series
        try:
            ex_dt = datetime.strptime(ex, "%d-%b-%Y").strftime("%Y-%m-%d")
        except Exception:
            continue
        rec = {"ex_date": ex_dt, "kind": kind, "detail": detail, "subject": subj}
        if f is None:
            # rights and demergers are EXPECTED here — their factor is measured
            # from the price at this known ex-date, not read from the text.
            rec["needs_derivation"] = kind in ("rights", "demerger")
            unparsed.append(rec)
        else:
            rec["factor"] = round(f, 8)
            rec["source"] = "announcement"
            actions.append(rec)
    actions.sort(key=lambda x: x["ex_date"])
    unparsed.sort(key=lambda x: x["ex_date"])
    return {"symbol": sym, "actions": actions, "unparsed": unparsed,
            "fetched": datetime.now().isoformat()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    syms = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
            else sorted(f[:-4] for f in os.listdir(HIST) if f.endswith(".pkl")))
    if args.limit:
        syms = syms[: args.limit]
    todo = [s for s in syms if args.force or not os.path.exists(os.path.join(OUT, f"{s}.json"))]
    log(f"{len(todo)} symbols to fetch ({len(syms) - len(todo)} already done)")

    sess = session()
    ok = err = 0
    n_actions = n_unparsed = 0
    since = 0
    for i, sym in enumerate(todo, 1):
        if since >= 120:
            sess = session(); since = 0; time.sleep(1)
        since += 1
        try:
            res = fetch_symbol(sess, sym)
        except Exception as e:
            err += 1
            res = None
        if res is None:
            err += 1
        else:
            ok += 1
            n_actions += len(res["actions"])
            n_unparsed += len(res["unparsed"])
            p = os.path.join(OUT, f"{sym}.json")
            json.dump(res, open(p + ".tmp", "w"), indent=1)
            os.replace(p + ".tmp", p)
        if i % 50 == 0:
            log(f"  {i}/{len(todo)} · ok {ok} err {err} · "
                f"{n_actions} actions, {n_unparsed} unparsed")
        time.sleep(args.sleep)
    log(f"done: ok {ok} · errors {err} · {n_actions} actions · {n_unparsed} unparsed")


if __name__ == "__main__":
    main()

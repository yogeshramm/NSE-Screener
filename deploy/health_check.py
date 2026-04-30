#!/usr/bin/env python3
"""
Daily health check — runs after morning warm (8:00 AM IST).
Tests: data freshness, cache warm, screen response, Groq connectivity.
Logs pass/fail to data_store/health_check.log.
Auto-fixes: triggers warm if cache cold, triggers catchup if data stale.
"""
import sys, json, time, requests
from datetime import datetime, date
from pathlib import Path

BASE = "http://localhost:8000"
LOG  = Path(__file__).parent.parent / "data_store" / "health_check.log"

# Known bugs + fixes playbook — updated as issues are discovered
PLAYBOOK = {
    "CACHE_COLD":    "Cache not warm after morning cycle. Triggering /data/warm.",
    "STALE_DATA":    "Data gap > 4 days. Triggering /data/catchup.",
    "SCREEN_ZERO":   "Scan returned 0 results. Possible: wrong preset, cache miss, or screener bug.",
    "SCREEN_SLOW":   "Scan took >20s. Possible: cache miss or json.dumps Response wrapper removed.",
    "SCREEN_FAIL":   "POST /screen returned non-200. Check server logs.",
    "GROQ_MISSING":  "No GROQ_API_KEY in environment. Check /etc/yointell.env.",
    "STATUS_FAIL":   "GET /data/status failed. Server may be down.",
    "WARM_STUCK":    "warm_in_progress=True for >30min. Stale flag — restart may be needed.",
}


def _post(path, **kwargs):
    return requests.post(f"{BASE}{path}", timeout=30, **kwargs)

def _get(path, **kwargs):
    return requests.get(f"{BASE}{path}", timeout=10, **kwargs)


def run():
    ok, errors = [], []

    # ── 1. Server status ──────────────────────────────────────────────────────
    try:
        d = _get("/data/status").json()
        cache_warm       = d.get("cache_warm")
        warm_in_progress = d.get("warm_in_progress")
        data_as_of       = d.get("history_latest_date") or d.get("data_as_of")
        cache_pct        = d.get("cache_warm_pct", 0)

        if warm_in_progress:
            errors.append("WARM_STUCK")
        if not cache_warm:
            errors.append("CACHE_COLD")
            try:
                _post("/data/warm?scope=nifty500")
                ok.append("AUTO-FIX: triggered /data/warm")
            except Exception: pass

        if data_as_of:
            gap = (date.today() - datetime.strptime(data_as_of, "%Y-%m-%d").date()).days
            if gap > 4:
                errors.append(f"STALE_DATA (gap={gap}d, as_of={data_as_of})")
                try:
                    _post("/data/catchup")
                    ok.append("AUTO-FIX: triggered /data/catchup")
                except Exception: pass
            else:
                ok.append(f"data fresh: {data_as_of} (gap={gap}d)")
        else:
            errors.append("STALE_DATA (no date)")

        ok.append(f"cache: {'warm' if cache_warm else 'COLD'} {cache_pct}%")
    except Exception as e:
        errors.append(f"STATUS_FAIL: {e}")

    # ── 2. Screen test ────────────────────────────────────────────────────────
    try:
        # Load original_formula preset config
        config = {}
        try:
            cr = _get("/presets/original_formula").json()
            config = cr.get("config", {})
        except Exception: pass

        t0 = time.time()
        r = _post("/screen", json={"config": config, "scope": "nifty500"})
        elapsed = round(time.time() - t0, 1)

        if r.status_code != 200:
            errors.append(f"SCREEN_FAIL: HTTP {r.status_code}")
        else:
            d = r.json()
            stage1 = d.get("stage1_passed") or len(d.get("stage1_results", []))
            if stage1 == 0:
                errors.append(f"SCREEN_ZERO ({elapsed}s)")
            elif elapsed > 20:
                errors.append(f"SCREEN_SLOW: {elapsed}s")
            else:
                ok.append(f"screen: {stage1} results in {elapsed}s")
    except Exception as e:
        errors.append(f"SCREEN_FAIL: {e}")

    # ── 3. Groq connectivity ──────────────────────────────────────────────────
    try:
        d = _get("/chat/status").json()
        if not d.get("groq"):
            errors.append("GROQ_MISSING")
        else:
            ok.append(f"groq: {d.get('model')} ready")
    except Exception as e:
        errors.append(f"GROQ_FAIL: {e}")

    # ── Write log ─────────────────────────────────────────────────────────────
    ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "PASS" if not errors else "FAIL"
    lines  = [f"\n{'='*60}", f"{ts}  [{status}]"]
    for msg in ok:
        lines.append(f"  ✓ {msg}")
    for err in errors:
        tag  = err.split(":")[0].split("(")[0].strip()
        hint = PLAYBOOK.get(tag, "")
        lines.append(f"  ✗ {err}" + (f" → {hint}" if hint else ""))

    entry = "\n".join(lines) + "\n"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(entry)
    print(entry)
    return errors


if __name__ == "__main__":
    errs = run()
    sys.exit(1 if errs else 0)

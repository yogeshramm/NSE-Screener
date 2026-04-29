#!/usr/bin/env python3
"""Pre-warm screener cache for all presets (Nifty 500 scope).
Runs nightly after the daily_download cron so first-click of any preset is instant."""
import json, urllib.request, time, os, glob

PRESET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "presets")
API = "http://localhost:8000"

def main():
    presets = [os.path.basename(p).replace(".json","") for p in glob.glob(f"{PRESET_DIR}/*.json")]
    print(f"[prewarm] {len(presets)} presets")
    for p in presets:
        try:
            cfg = json.loads(urllib.request.urlopen(f"{API}/presets/{p}", timeout=10).read())
            body = json.dumps({"config": cfg["config"], "scope":"nifty500"}).encode()
            req = urllib.request.Request(f"{API}/screen", data=body, headers={"Content-Type":"application/json"})
            t0 = time.time()
            r = urllib.request.urlopen(req, timeout=300).read()
            d = json.loads(r)
            print(f"[prewarm] {p}: {time.time()-t0:.1f}s s1={len(d.get('stage1_results',[]))} s2={len(d.get('stage2_results',[]))}")
        except Exception as e:
            print(f"[prewarm] {p}: FAIL — {e}")

if __name__ == "__main__":
    main()

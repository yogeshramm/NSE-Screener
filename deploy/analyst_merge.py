"""
Merge analyst cache after git reset --hard in deploy.
Called by .github/workflows/deploy.yml.

Server backup (rich MC/screener_eps data) is the base;
GHA's fresh trendlyne/tickertape fields are overlaid on top.
"""
import json
from pathlib import Path

backup_dir = Path("/tmp/yointell_runtime/analyst")
live_dir   = Path("/home/yointell/NSE-Screener/data_store/analyst")

merged = failed = 0
for gha_path in live_dir.glob("*__1y.json"):
    bak_path = backup_dir / gha_path.name
    if not bak_path.exists():
        continue  # new stock added by GHA — keep GHA version as-is
    try:
        gha = json.loads(gha_path.read_text())
        bak = json.loads(bak_path.read_text())
        out = {**bak}  # base = server backup (has MC, screener_eps, tt_forecasts)
        if gha.get("trendlyne"):   out["trendlyne"]   = gha["trendlyne"]
        if gha.get("tickertape"):  out["tickertape"]   = gha["tickertape"]
        if gha.get("_gh_updated"): out["_gh_updated"]  = gha["_gh_updated"]
        gha_path.write_text(json.dumps(out))
        merged += 1
    except Exception:
        failed += 1

total = sum(1 for _ in live_dir.glob("*__1y.json"))
print(f"Analyst cache merge: {merged} merged, {failed} failed, {total - merged - failed} gha-only kept")

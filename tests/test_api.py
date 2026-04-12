"""
Session 4 — API Endpoint Tests
Tests all FastAPI endpoints programmatically.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)


def print_header(title: str):
    print(f"\n{'#'*70}")
    print(f"#  {title}")
    print(f"{'#'*70}")


def test_health():
    print_header("TEST 1: GET / (Health Check)")
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    print(f"  Status: {data['status']}")
    print(f"  Indicators: {data['total_indicators']}")
    assert data["total_indicators"] == 25
    return True


def test_indicators_available():
    print_header("TEST 2: GET /indicators/available")
    r = client.get("/indicators/available")
    assert r.status_code == 200
    data = r.json()
    print(f"  Total: {data['total']}")
    print(f"  Most Precise: {data['tiers']['most_precise']}")
    print(f"  Hidden Gems: {data['tiers']['hidden_gem']}")
    print(f"  Highlighted: {data['tiers']['highlighted']}")
    assert data["total"] == 25
    assert len(data["tiers"]["highlighted"]) == 3
    return True


def test_indicators_filtered():
    print_header("TEST 3: GET /indicators/available?highlighted_only=true")
    r = client.get("/indicators/available?highlighted_only=true")
    data = r.json()
    print(f"  Highlighted: {[i['name'] for i in data['indicators']]}")
    assert data["total"] == 3
    return True


def test_config_default():
    print_header("TEST 4: GET /config/default")
    r = client.get("/config/default")
    assert r.status_code == 200
    data = r.json()
    print(f"  Filters: {data['total_filters']}")
    print(f"  Params: {data['total_params']}")
    assert data["total_filters"] >= 39
    return True


def test_presets_crud():
    print_header("TEST 5: Preset CRUD (save/list/load/delete)")

    # Save
    r = client.post("/presets/save", json={
        "name": "api_test_preset",
        "config": {"rsi": {"rsi_min": 40, "rsi_max": 75}}
    })
    assert r.status_code == 200
    print(f"  Save: {r.json()['status']}")

    # List
    r = client.get("/presets/list")
    presets = r.json()["presets"]
    print(f"  List: {presets}")
    assert "api_test_preset" in presets

    # Load
    r = client.get("/presets/api_test_preset")
    assert r.status_code == 200
    loaded = r.json()["config"]
    print(f"  Load: RSI min={loaded['rsi']['rsi_min']}, max={loaded['rsi']['rsi_max']}")
    assert loaded["rsi"]["rsi_min"] == 40

    # Delete
    r = client.delete("/presets/api_test_preset")
    assert r.status_code == 200
    print(f"  Delete: {r.json()['status']}")

    # Verify deleted
    r = client.get("/presets/api_test_preset")
    assert r.status_code == 404
    print(f"  Verify deleted: 404 OK")

    return True


def test_preset_not_found():
    print_header("TEST 6: GET /presets/nonexistent (404)")
    r = client.get("/presets/nonexistent")
    assert r.status_code == 404
    print(f"  Status: {r.status_code} — {r.json()['detail']}")
    return True


def test_custom_indicator():
    print_header("TEST 7: POST /indicators/custom")
    code = """
def compute(df, params):
    period = params.get('period', 10)
    sma = df['Close'].rolling(period).mean().iloc[-1]
    close = df['Close'].iloc[-1]
    return {'close': round(close, 2), 'sma': round(sma, 2), 'above': close > sma}

def check(computed, params):
    return {
        'status': 'PASS' if computed['above'] else 'FAIL',
        'value': f"Close={computed['close']} vs SMA={computed['sma']}",
        'threshold': 'Close above SMA',
        'details': f"Above: {computed['above']}"
    }
"""
    r = client.post("/indicators/custom", json={
        "name": "Custom SMA Check",
        "description": "Test custom indicator via API",
        "code": code,
        "params": {"period": 10},
    })
    assert r.status_code == 200
    data = r.json()
    print(f"  Registered: {data['name']}")
    print(f"  Type: {data['type']}")

    # Verify it shows up in available
    r2 = client.get("/indicators/available")
    names = [i["name"] for i in r2.json()["indicators"]]
    assert "Custom SMA Check" in names
    print(f"  Found in registry: YES (total now: {r2.json()['total']})")

    return True


def test_screen_empty():
    print_header("TEST 8: POST /screen (empty symbols)")
    r = client.post("/screen", json={"symbols": []})
    assert r.status_code == 400
    print(f"  Status: {r.status_code} — validation works")
    return True


def test_docs_endpoint():
    print_header("TEST 9: GET /docs (Swagger UI)")
    r = client.get("/docs")
    assert r.status_code == 200
    print(f"  Swagger UI: accessible ({len(r.text)} bytes)")
    return True


def run_all_tests():
    print("\n" + "="*70)
    print("  NSE SCREENER — SESSION 4 API ENDPOINT TESTS")
    print("="*70)

    tests = [
        ("Health check", test_health),
        ("Indicators available", test_indicators_available),
        ("Indicators filtered", test_indicators_filtered),
        ("Default config", test_config_default),
        ("Presets CRUD", test_presets_crud),
        ("Preset not found", test_preset_not_found),
        ("Custom indicator", test_custom_indicator),
        ("Screen validation", test_screen_empty),
        ("Swagger docs", test_docs_endpoint),
    ]

    results = []
    for name, fn in tests:
        try:
            ok = fn()
            results.append((name, ok))
        except Exception as e:
            print(f"\n  EXCEPTION: {e}")
            results.append((name, False))

    print_header("FINAL STATUS SUMMARY")
    all_pass = True
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {name:<25s}: {status}")

    print(f"\n  Overall: {'ALL OK' if all_pass else 'HAS ISSUES'}")
    print(f"\n{'='*70}")
    print("  SESSION 4 API ENDPOINT TESTS COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run_all_tests()

"""
Candlestick pattern library and detection.

All detectors take a list of candles [{open, high, low, close}] and return
True when the pattern is formed at the last candle, optionally with a
confidence score.

Synthetic snippets are hand-crafted OHLC sequences that cleanly illustrate
each pattern — the frontend renders them as small canvas charts in the
pattern library cards. No external images.

Accuracy figures are from Thomas Bulkowski's "Encyclopedia of Candlestick
Charts" (tested on 4.7M+ candles) unless noted.
"""

import os
import pickle
from typing import List, Dict, Any, Optional


HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_store", "history")


# ---------- Helpers on a single candle ----------
def _body(c):   return abs(c["close"] - c["open"])
def _range(c):  return c["high"] - c["low"]
def _upper(c):  return c["high"] - max(c["open"], c["close"])
def _lower(c):  return min(c["open"], c["close"]) - c["low"]
def _green(c):  return c["close"] > c["open"]
def _red(c):    return c["close"] < c["open"]
def _mid(c):    return (c["open"] + c["close"]) / 2


# ---------- Individual detectors ----------
def is_doji(c, **_):
    r = _range(c)
    return r > 0 and _body(c) <= r * 0.1

def is_hammer(c, **_):
    r = _range(c)
    if r == 0:
        return False
    b = _body(c)
    return _lower(c) >= 2 * b and _upper(c) <= b * 0.3 and b >= r * 0.15

def is_shooting_star(c, **_):
    r = _range(c)
    if r == 0:
        return False
    b = _body(c)
    return _upper(c) >= 2 * b and _lower(c) <= b * 0.3 and b >= r * 0.15

def is_bullish_engulfing(prev, cur, **_):
    return (_red(prev) and _green(cur)
            and cur["open"] <= prev["close"]
            and cur["close"] >= prev["open"]
            and _body(cur) > _body(prev))

def is_bearish_engulfing(prev, cur, **_):
    return (_green(prev) and _red(cur)
            and cur["open"] >= prev["close"]
            and cur["close"] <= prev["open"]
            and _body(cur) > _body(prev))

def is_morning_star(a, b, c, **_):
    return (_red(a)
            and _body(b) <= _body(a) * 0.5
            and _green(c)
            and c["close"] > _mid(a))

def is_evening_star(a, b, c, **_):
    return (_green(a)
            and _body(b) <= _body(a) * 0.5
            and _red(c)
            and c["close"] < _mid(a))

def is_three_white_soldiers(a, b, c, **_):
    return (_green(a) and _green(b) and _green(c)
            and b["close"] > a["close"] and c["close"] > b["close"]
            and _body(a) > _range(a) * 0.4
            and _body(b) > _range(b) * 0.4
            and _body(c) > _range(c) * 0.4)

def is_three_black_crows(a, b, c, **_):
    return (_red(a) and _red(b) and _red(c)
            and b["close"] < a["close"] and c["close"] < b["close"]
            and _body(a) > _range(a) * 0.4
            and _body(b) > _range(b) * 0.4
            and _body(c) > _range(c) * 0.4)

def is_piercing_line(prev, cur, **_):
    # Bullish: red then green that opens below prev low and closes above midpoint of prev body
    return (_red(prev) and _green(cur)
            and cur["open"] < prev["low"]
            and cur["close"] > (prev["open"] + prev["close"]) / 2
            and cur["close"] < prev["open"])

def is_dark_cloud_cover(prev, cur, **_):
    return (_green(prev) and _red(cur)
            and cur["open"] > prev["high"]
            and cur["close"] < (prev["open"] + prev["close"]) / 2
            and cur["close"] > prev["open"])


# ---------- Pattern library ----------
PATTERNS = [
    {
        "key": "three_white_soldiers",
        "name": "Three White Soldiers",
        "candles": 3,
        "direction": "bullish",
        "type": "continuation",
        "accuracy": 82,
        "description": (
            "Three consecutive strong green candles, each closing higher than the last, "
            "with small upper wicks. Signals strong sustained buying pressure after a "
            "consolidation or mild downtrend."
        ),
        "confirm": "Rising volume over the three days; RSI crossing above 50; price above SMA 20.",
        "invalidate": "Next candle closes below the low of the middle soldier.",
        "detect_n": 3,
    },
    {
        "key": "three_black_crows",
        "name": "Three Black Crows",
        "candles": 3,
        "direction": "bearish",
        "type": "continuation",
        "accuracy": 78,
        "description": (
            "Three consecutive strong red candles, each closing lower than the last, "
            "with small lower wicks. Signals strong sustained selling after an uptrend."
        ),
        "confirm": "Rising volume; RSI crossing below 50; price breaking SMA 20.",
        "invalidate": "Next candle closes above the high of the middle crow.",
        "detect_n": 3,
    },
    {
        "key": "morning_star",
        "name": "Morning Star",
        "candles": 3,
        "direction": "bullish",
        "type": "reversal",
        "accuracy": 78,
        "description": (
            "Three-candle bullish reversal: a big red candle, then a small-bodied candle "
            "(often gapping down), then a big green candle closing past the midpoint of "
            "the first red. Classic bottom reversal pattern."
        ),
        "confirm": "Third candle with high volume; RSI rising from oversold; near support.",
        "invalidate": "Price falls below the low of the middle candle.",
        "detect_n": 3,
    },
    {
        "key": "evening_star",
        "name": "Evening Star",
        "candles": 3,
        "direction": "bearish",
        "type": "reversal",
        "accuracy": 72,
        "description": (
            "Three-candle bearish reversal: big green candle, small-bodied (often "
            "gapping up), then a big red candle closing past the midpoint of the first "
            "green. Classic top reversal."
        ),
        "confirm": "Third candle with high volume; RSI falling from overbought; near resistance.",
        "invalidate": "Price closes above the high of the middle candle.",
        "detect_n": 3,
    },
    {
        "key": "bullish_engulfing",
        "name": "Bullish Engulfing",
        "candles": 2,
        "direction": "bullish",
        "type": "reversal",
        "accuracy": 65,
        "description": (
            "A small red candle fully engulfed by a large green candle. The green body "
            "must open at or below prior close and close above prior open. Signals buyers "
            "overwhelming sellers after a downtrend."
        ),
        "confirm": "Volume spike on the engulfing candle; near support or oversold RSI.",
        "invalidate": "Price closes back below the low of the engulfing candle.",
        "detect_n": 2,
    },
    {
        "key": "bearish_engulfing",
        "name": "Bearish Engulfing",
        "candles": 2,
        "direction": "bearish",
        "type": "reversal",
        "accuracy": 65,
        "description": (
            "A small green candle fully engulfed by a large red candle. Signals sellers "
            "overwhelming buyers after an uptrend."
        ),
        "confirm": "Volume spike on the engulfing candle; near resistance or overbought RSI.",
        "invalidate": "Price closes back above the high of the engulfing candle.",
        "detect_n": 2,
    },
    {
        "key": "piercing_line",
        "name": "Piercing Line",
        "candles": 2,
        "direction": "bullish",
        "type": "reversal",
        "accuracy": 64,
        "description": (
            "Red candle followed by a green candle that opens below prior low and closes "
            "above the midpoint of the prior red body. A bottom reversal signal."
        ),
        "confirm": "Increasing volume; oversold RSI; near support zone.",
        "invalidate": "Price falls below the low of the piercing candle.",
        "detect_n": 2,
    },
    {
        "key": "dark_cloud_cover",
        "name": "Dark Cloud Cover",
        "candles": 2,
        "direction": "bearish",
        "type": "reversal",
        "accuracy": 63,
        "description": (
            "Green candle followed by a red candle that opens above prior high and closes "
            "below the midpoint of the prior green body. A top reversal signal."
        ),
        "confirm": "Increasing volume; overbought RSI; near resistance zone.",
        "invalidate": "Price rises above the high of the dark cloud candle.",
        "detect_n": 2,
    },
    {
        "key": "hammer",
        "name": "Hammer",
        "candles": 1,
        "direction": "bullish",
        "type": "reversal",
        "accuracy": 60,
        "description": (
            "Single candle with a small body near the top and a long lower wick (at "
            "least 2× the body). Signals buyers rejecting lower prices after a downtrend."
        ),
        "confirm": "Next candle closes green and above the hammer's high.",
        "invalidate": "Price closes below the low of the hammer.",
        "detect_n": 1,
    },
    {
        "key": "shooting_star",
        "name": "Shooting Star",
        "candles": 1,
        "direction": "bearish",
        "type": "reversal",
        "accuracy": 59,
        "description": (
            "Single candle with a small body near the bottom and a long upper wick (at "
            "least 2× the body). Signals sellers rejecting higher prices after an uptrend."
        ),
        "confirm": "Next candle closes red and below the shooting star's low.",
        "invalidate": "Price closes above the high of the shooting star.",
        "detect_n": 1,
    },
    {
        "key": "doji",
        "name": "Doji",
        "candles": 1,
        "direction": "neutral",
        "type": "indecision",
        "accuracy": 55,
        "description": (
            "Single candle where open and close are nearly equal. Indicates indecision "
            "and potential reversal at extremes. By itself a weak signal — always wait "
            "for the next candle to confirm direction."
        ),
        "confirm": "Context: at support (bullish potential) or resistance (bearish potential). Confirmation comes from the next candle closing decisively in one direction.",
        "invalidate": "Ambiguous — this is an indecision signal; wait for next candle.",
        "detect_n": 1,
    },
]


# Synthetic OHLC sequences that cleanly illustrate each pattern.
# Values are intentionally simple; the frontend renders these as mini candlestick snippets.
SNIPPETS = {
    "hammer": [
        {"open": 100, "high": 101, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 100, "low": 97, "close": 97.5},
        {"open": 97.5, "high": 98, "low": 96, "close": 96.5},
        # Hammer candle: small body near top, long lower wick
        {"open": 96.5, "high": 97.2, "low": 93, "close": 97.0},
        {"open": 97, "high": 99, "low": 96.8, "close": 98.8},
    ],
    "shooting_star": [
        {"open": 96, "high": 97, "low": 95.5, "close": 96.8},
        {"open": 96.8, "high": 98, "low": 96.5, "close": 97.8},
        {"open": 97.8, "high": 99.5, "low": 97.5, "close": 99.2},
        # Shooting star: small body near bottom, long upper wick
        {"open": 99.2, "high": 103, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 99.8, "low": 97, "close": 97.3},
    ],
    "bullish_engulfing": [
        {"open": 100, "high": 100.5, "low": 99, "close": 99.2},
        {"open": 99.2, "high": 99.3, "low": 97.5, "close": 97.8},
        {"open": 97.8, "high": 98, "low": 96.5, "close": 97.0},  # small red
        {"open": 96.8, "high": 99.5, "low": 96.5, "close": 99.2},  # big green engulfing
        {"open": 99.2, "high": 100.2, "low": 99.0, "close": 100.0},
    ],
    "bearish_engulfing": [
        {"open": 96, "high": 96.5, "low": 95, "close": 96.3},
        {"open": 96.3, "high": 97.5, "low": 96.2, "close": 97.3},
        {"open": 97.3, "high": 98.5, "low": 97.2, "close": 98.2},  # small green
        {"open": 98.5, "high": 98.8, "low": 96.5, "close": 96.8},  # big red engulfing
        {"open": 96.8, "high": 97, "low": 95.5, "close": 95.7},
    ],
    "morning_star": [
        {"open": 102, "high": 102.5, "low": 100, "close": 100.2},
        {"open": 100.2, "high": 100.3, "low": 97, "close": 97.3},  # big red
        {"open": 96.5, "high": 97.2, "low": 96.2, "close": 96.8},  # small doji-ish, gap down
        {"open": 97, "high": 100.5, "low": 96.8, "close": 100.2},  # big green past midpoint
        {"open": 100.2, "high": 101, "low": 100, "close": 100.8},
    ],
    "evening_star": [
        {"open": 96, "high": 96.5, "low": 95, "close": 96.3},
        {"open": 96.3, "high": 100, "low": 96.2, "close": 99.8},  # big green
        {"open": 100.5, "high": 100.8, "low": 100.2, "close": 100.6},  # small, gap up
        {"open": 100.2, "high": 100.3, "low": 96.5, "close": 96.8},  # big red past midpoint
        {"open": 96.8, "high": 97, "low": 95.5, "close": 95.7},
    ],
    "three_white_soldiers": [
        {"open": 96, "high": 96.5, "low": 95, "close": 95.5},
        {"open": 95.5, "high": 96, "low": 95, "close": 95.3},
        {"open": 95.3, "high": 97, "low": 95.2, "close": 96.8},
        {"open": 96.9, "high": 98.5, "low": 96.8, "close": 98.3},
        {"open": 98.4, "high": 100, "low": 98.2, "close": 99.8},
    ],
    "three_black_crows": [
        {"open": 100, "high": 100.5, "low": 99.5, "close": 100.3},
        {"open": 100.3, "high": 100.5, "low": 100, "close": 100.4},
        {"open": 100.4, "high": 100.5, "low": 98.8, "close": 99.0},
        {"open": 98.9, "high": 99, "low": 97.2, "close": 97.4},
        {"open": 97.3, "high": 97.4, "low": 95.8, "close": 96.0},
    ],
    "piercing_line": [
        {"open": 100, "high": 100.3, "low": 98.5, "close": 98.8},
        {"open": 98.8, "high": 99, "low": 97, "close": 97.2},  # red
        {"open": 96.5, "high": 98.5, "low": 96.3, "close": 98.3},  # piercing green: opens below prev low, closes past midpoint
        {"open": 98.3, "high": 99, "low": 98, "close": 98.8},
        {"open": 98.8, "high": 99.5, "low": 98.5, "close": 99.2},
    ],
    "dark_cloud_cover": [
        {"open": 96, "high": 96.5, "low": 95.5, "close": 96.3},
        {"open": 96.3, "high": 98.5, "low": 96.2, "close": 98.3},  # green
        {"open": 98.8, "high": 99, "low": 96.8, "close": 97.0},  # dark cloud: opens above prev high, closes past midpoint
        {"open": 97, "high": 97.3, "low": 96, "close": 96.2},
        {"open": 96.2, "high": 96.4, "low": 95, "close": 95.3},
    ],
    "doji": [
        {"open": 100, "high": 100.5, "low": 99.5, "close": 100.3},
        {"open": 100.3, "high": 100.5, "low": 99, "close": 99.5},
        {"open": 99.5, "high": 100.2, "low": 99.2, "close": 99.55},  # doji: open ≈ close, with wicks
        {"open": 99.6, "high": 100, "low": 99.3, "close": 99.8},
        {"open": 99.8, "high": 100.2, "low": 99.5, "close": 100.0},
    ],
}


def list_patterns() -> List[Dict[str, Any]]:
    """Return the full library with synthetic snippets attached."""
    out = []
    for p in PATTERNS:
        out.append({**p, "snippet": SNIPPETS.get(p["key"], [])})
    return out


def detect_at_end(pattern_key: str, candles: List[Dict[str, float]]) -> bool:
    """Check if the given pattern is formed at the LAST candle of the series."""
    if not candles:
        return False
    n = len(candles)
    if pattern_key == "hammer" and n >= 1:
        return is_hammer(candles[-1])
    if pattern_key == "shooting_star" and n >= 1:
        return is_shooting_star(candles[-1])
    if pattern_key == "doji" and n >= 1:
        return is_doji(candles[-1])
    if pattern_key == "bullish_engulfing" and n >= 2:
        return is_bullish_engulfing(candles[-2], candles[-1])
    if pattern_key == "bearish_engulfing" and n >= 2:
        return is_bearish_engulfing(candles[-2], candles[-1])
    if pattern_key == "piercing_line" and n >= 2:
        return is_piercing_line(candles[-2], candles[-1])
    if pattern_key == "dark_cloud_cover" and n >= 2:
        return is_dark_cloud_cover(candles[-2], candles[-1])
    if pattern_key == "morning_star" and n >= 3:
        return is_morning_star(candles[-3], candles[-2], candles[-1])
    if pattern_key == "evening_star" and n >= 3:
        return is_evening_star(candles[-3], candles[-2], candles[-1])
    if pattern_key == "three_white_soldiers" and n >= 3:
        return is_three_white_soldiers(candles[-3], candles[-2], candles[-1])
    if pattern_key == "three_black_crows" and n >= 3:
        return is_three_black_crows(candles[-3], candles[-2], candles[-1])
    return False


def scan_universe(pattern_key: str, symbols: List[str], lookback: int = 5) -> List[Dict[str, Any]]:
    """
    Scan the given symbols for the pattern forming in the last `lookback` bars.
    Returns list of {symbol, days_ago, last_close, pct_change_5d}.
    """
    hits = []
    for sym in symbols:
        fpath = os.path.join(HISTORY_DIR, f"{sym}.pkl")
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "rb") as f:
                df = pickle.load(f)
            df = df[~df.index.duplicated(keep="last")]
            if len(df) < 10:
                continue
            # Convert last `lookback + 5` bars to list of dicts so we can slice
            window = df.tail(lookback + 5)
            bars = [{"open": float(r["Open"]), "high": float(r["High"]),
                     "low": float(r["Low"]), "close": float(r["Close"])}
                    for _, r in window.iterrows()]
            # Check each ending position in the last `lookback` bars
            for back in range(0, lookback):
                end = len(bars) - back
                sub = bars[:end]
                if detect_at_end(pattern_key, sub):
                    last = bars[end - 1]
                    # % change over the 5 bars ending at this point
                    if end >= 6:
                        prev5 = bars[end - 6]
                        pct5 = (last["close"] - prev5["close"]) / prev5["close"] * 100
                    else:
                        pct5 = None
                    hits.append({
                        "symbol": sym,
                        "days_ago": back,
                        "last_close": round(last["close"], 2),
                        "pct_change_5d": round(pct5, 2) if pct5 is not None else None,
                    })
                    break
        except Exception:
            continue
    # Today's matches first, then by recency
    hits.sort(key=lambda x: (x["days_ago"], x["symbol"]))
    return hits

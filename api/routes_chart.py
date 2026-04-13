"""
GET /chart/{symbol} — Returns OHLCV + indicator data as JSON for charting.
"""

from fastapi import APIRouter, HTTPException
from api.data_helper import get_stock_bundle

router = APIRouter()


@router.get("/chart/{symbol}")
def get_chart_data(symbol: str, days: int = 200):
    """Returns OHLCV candlestick data + computed indicator overlays for charting."""
    symbol = symbol.strip().upper()
    try:
        bundle = get_stock_bundle(symbol)
    except Exception as e:
        raise HTTPException(502, f"No data for {symbol}: {e}")

    df = bundle["daily_df"]
    if df is None or len(df) < 5:
        raise HTTPException(404, f"Insufficient data for {symbol}")

    # Limit to requested days
    df = df.iloc[-days:]

    # OHLCV candles
    candles = []
    for idx, row in df.iterrows():
        t = int(idx.timestamp()) if hasattr(idx, 'timestamp') else 0
        candles.append({
            "time": t,
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
        })

    # Volume
    volumes = []
    for idx, row in df.iterrows():
        t = int(idx.timestamp()) if hasattr(idx, 'timestamp') else 0
        color = "#00d4aa" if row["Close"] >= row["Open"] else "#ff4757"
        volumes.append({"time": t, "value": int(row["Volume"]), "color": color})

    # EMA 50 & 200
    ema50 = df["Close"].ewm(span=50, adjust=False).mean()
    ema200 = df["Close"].ewm(span=200, adjust=False).mean()
    ema50_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                  for idx, v in ema50.items() if not __import__('math').isnan(v)]
    ema200_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                   for idx, v in ema200.items() if not __import__('math').isnan(v)]

    # Supertrend (simplified — just the line)
    import pandas as pd
    period, mult = 7, 3.0
    hl2 = (df["High"] + df["Low"]) / 2
    tr = pd.concat([df["High"] - df["Low"],
                     (df["High"] - df["Close"].shift()).abs(),
                     (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(1, index=df.index)
    for i in range(period, len(df)):
        if i == period:
            st.iloc[i] = lower.iloc[i]
        elif st.iloc[i-1] == upper.iloc[i-1]:
            st.iloc[i] = upper.iloc[i] if df["Close"].iloc[i] <= upper.iloc[i] else lower.iloc[i]
            direction.iloc[i] = -1 if df["Close"].iloc[i] <= upper.iloc[i] else 1
        else:
            st.iloc[i] = lower.iloc[i] if df["Close"].iloc[i] >= lower.iloc[i] else upper.iloc[i]
            direction.iloc[i] = 1 if df["Close"].iloc[i] >= lower.iloc[i] else -1
    st_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
               for idx, v in st.items() if not pd.isna(v)]

    # RSI
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                for idx, v in rsi.items() if not pd.isna(v)]

    return {
        "symbol": symbol,
        "candles": candles,
        "volumes": volumes,
        "overlays": {
            "ema50": ema50_data,
            "ema200": ema200_data,
            "supertrend": st_data,
        },
        "panels": {
            "rsi": rsi_data,
        },
        "price": round(df["Close"].iloc[-1], 2),
        "bars": len(candles),
    }

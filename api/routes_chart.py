"""
GET /chart/{symbol} — Returns OHLCV + indicator data as JSON for charting.
"""

from fastapi import APIRouter, HTTPException
from api.data_helper import get_stock_bundle

router = APIRouter()


@router.get("/chart/{symbol}")
def get_chart_data(symbol: str, days: int = 200, interval: str = "1D"):
    """Returns OHLCV candlestick data + computed indicator overlays for charting.
    interval: '1D' (daily), '1W' (weekly), '1M' (monthly)
    """
    symbol = symbol.strip().upper()
    try:
        bundle = get_stock_bundle(symbol)
    except Exception as e:
        raise HTTPException(502, f"No data for {symbol}: {e}")

    import pandas as pd
    from datetime import date

    df_full = bundle["daily_df"]
    if df_full is None or len(df_full) < 5:
        raise HTTPException(404, f"Insufficient data for {symbol}")

    # Use ALL data for indicator computation, limit display range later
    df = df_full.copy()

    # Resample to weekly or monthly if requested
    if interval == "1W":
        df = df.resample("W").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
        if len(df) and df.index[-1].date() > date.today():
            df.index = df.index[:-1].append(pd.DatetimeIndex([date.today()]))
    elif interval == "1M":
        df = df.resample("ME").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
        if len(df) and df.index[-1].date() > date.today():
            df.index = df.index[:-1].append(pd.DatetimeIndex([date.today()]))

    # How many bars to display (compute on all, display last N)
    display_bars = days if interval == "1D" else (days // 7 if interval == "1W" else days // 30)
    display_bars = max(display_bars, 5)

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

    # SMA 20
    sma20 = df["Close"].rolling(window=20).mean()
    sma20_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                  for idx, v in sma20.items() if not pd.isna(v)]

    # Bollinger Bands (20, 2)
    bb_mid = df["Close"].rolling(window=20).mean()
    bb_std = df["Close"].rolling(window=20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_upper_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                     for idx, v in bb_upper.items() if not pd.isna(v)]
    bb_mid_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                   for idx, v in bb_mid.items() if not pd.isna(v)]
    bb_lower_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                     for idx, v in bb_lower.items() if not pd.isna(v)]

    # VWAP (rolling 20-period)
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tp_vol = (typical * df["Volume"]).rolling(window=20).sum()
    cum_vol = df["Volume"].rolling(window=20).sum()
    vwap = cum_tp_vol / cum_vol
    vwap_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                 for idx, v in vwap.items() if not pd.isna(v)]

    # MACD (12, 26, 9)
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    macd_data = [{"time": int(idx.timestamp()), "value": round(v, 4)}
                 for idx, v in macd_line.items() if not pd.isna(v)]
    macd_signal_data = [{"time": int(idx.timestamp()), "value": round(v, 4)}
                        for idx, v in macd_signal.items() if not pd.isna(v)]
    macd_hist_data = [{"time": int(idx.timestamp()), "value": round(v, 4),
                       "color": "#00e5a0" if v >= 0 else "#ff4757"}
                      for idx, v in macd_hist.items() if not pd.isna(v)]

    # VWAP + SD Bands (1σ upper/lower)
    vwap_diff_sq = ((typical - vwap) ** 2).rolling(window=20).mean()
    vwap_sd = pd.np.sqrt(vwap_diff_sq) if hasattr(pd, 'np') else __import__('numpy').sqrt(vwap_diff_sq)
    vwap_upper = vwap + vwap_sd
    vwap_lower = vwap - vwap_sd
    vwap_upper_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                       for idx, v in vwap_upper.items() if not pd.isna(v)]
    vwap_lower_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                       for idx, v in vwap_lower.items() if not pd.isna(v)]

    # Ichimoku Cloud (9/26/52)
    h9 = df["High"].rolling(9).max(); l9 = df["Low"].rolling(9).min()
    tenkan = (h9 + l9) / 2
    h26 = df["High"].rolling(26).max(); l26 = df["Low"].rolling(26).min()
    kijun = (h26 + l26) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    h52 = df["High"].rolling(52).max(); l52 = df["Low"].rolling(52).min()
    senkou_b = ((h52 + l52) / 2).shift(26)
    tenkan_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                   for idx, v in tenkan.items() if not pd.isna(v)]
    kijun_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                  for idx, v in kijun.items() if not pd.isna(v)]
    senkou_a_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                     for idx, v in senkou_a.items() if not pd.isna(v)]
    senkou_b_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                     for idx, v in senkou_b.items() if not pd.isna(v)]

    # Pivot Levels (classic daily)
    prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    pp = (prev["High"] + prev["Low"] + prev["Close"]) / 3
    r1 = 2 * pp - prev["Low"]; s1 = 2 * pp - prev["High"]
    r2 = pp + (prev["High"] - prev["Low"]); s2 = pp - (prev["High"] - prev["Low"])

    # Stochastic RSI (14, 14, 3, 3)
    rsi_min = rsi.rolling(14).min(); rsi_max = rsi.rolling(14).max()
    stoch_rsi_k = ((rsi - rsi_min) / (rsi_max - rsi_min) * 100)
    stoch_rsi_d = stoch_rsi_k.rolling(3).mean()
    stoch_k_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                    for idx, v in stoch_rsi_k.items() if not pd.isna(v)]
    stoch_d_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                    for idx, v in stoch_rsi_d.items() if not pd.isna(v)]

    # Williams %R (14)
    h14 = df["High"].rolling(14).max(); l14 = df["Low"].rolling(14).min()
    williams = ((h14 - df["Close"]) / (h14 - l14)) * -100
    williams_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                     for idx, v in williams.items() if not pd.isna(v)]

    # ADX (14)
    import numpy as np
    plus_dm = df["High"].diff(); minus_dm = df["Low"].diff().abs()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm_s = df["Low"].shift() - df["Low"]
    minus_dm_s = minus_dm_s.where((minus_dm_s > plus_dm) & (minus_dm_s > 0), 0.0)
    atr14 = tr.ewm(alpha=1/14, min_periods=14).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr14)
    minus_di = 100 * (minus_dm_s.ewm(alpha=1/14, min_periods=14).mean() / atr14)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.ewm(alpha=1/14, min_periods=14).mean()
    adx_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                for idx, v in adx_val.items() if not pd.isna(v)]

    # OBV
    obv = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    obv_data = [{"time": int(idx.timestamp()), "value": int(v)}
                for idx, v in obv.items() if not pd.isna(v)]

    # CMF (20)
    mfm = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / (df["High"] - df["Low"]).replace(0, 1)
    mfv = mfm * df["Volume"]
    cmf = mfv.rolling(20).sum() / df["Volume"].rolling(20).sum()
    cmf_data = [{"time": int(idx.timestamp()), "value": round(v, 4)}
                for idx, v in cmf.items() if not pd.isna(v)]

    # ATR (14)
    atr_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                for idx, v in atr14.items() if not pd.isna(v)]

    # Awesome Oscillator (5/34)
    ao = hl2.rolling(5).mean() - hl2.rolling(34).mean()
    ao_data = [{"time": int(idx.timestamp()), "value": round(v, 2),
                "color": "#00e5a0" if v >= 0 else "#ff4757"}
               for idx, v in ao.items() if not pd.isna(v)]

    # ROC (9)
    roc = df["Close"].pct_change(9) * 100
    roc_data = [{"time": int(idx.timestamp()), "value": round(v, 2)}
                for idx, v in roc.items() if not pd.isna(v)]

    # Vortex (14)
    vm_plus = (df["High"] - df["Low"].shift()).abs()
    vm_minus = (df["Low"] - df["High"].shift()).abs()
    vi_plus = vm_plus.rolling(14).sum() / tr.rolling(14).sum()
    vi_minus = vm_minus.rolling(14).sum() / tr.rolling(14).sum()
    vortex_plus_data = [{"time": int(idx.timestamp()), "value": round(v, 4)}
                        for idx, v in vi_plus.items() if not pd.isna(v)]
    vortex_minus_data = [{"time": int(idx.timestamp()), "value": round(v, 4)}
                         for idx, v in vi_minus.items() if not pd.isna(v)]

    # Trim all arrays to display range (computed on full data, show last N)
    def trim(arr):
        return arr[-display_bars:] if isinstance(arr, list) and len(arr) > display_bars else arr

    return {
        "symbol": symbol,
        "candles": trim(candles),
        "volumes": trim(volumes),
        "overlays": {
            "ema50": trim(ema50_data),
            "ema200": trim(ema200_data),
            "supertrend": trim(st_data),
            "sma20": trim(sma20_data),
            "bb_upper": trim(bb_upper_data),
            "bb_mid": trim(bb_mid_data),
            "bb_lower": trim(bb_lower_data),
            "vwap": trim(vwap_data),
            "vwap_upper": trim(vwap_upper_data),
            "vwap_lower": trim(vwap_lower_data),
            "ichimoku_tenkan": trim(tenkan_data),
            "ichimoku_kijun": trim(kijun_data),
            "ichimoku_senkou_a": trim(senkou_a_data),
            "ichimoku_senkou_b": trim(senkou_b_data),
            "pivot_pp": round(pp, 2),
            "pivot_r1": round(r1, 2),
            "pivot_s1": round(s1, 2),
            "pivot_r2": round(r2, 2),
            "pivot_s2": round(s2, 2),
        },
        "panels": {
            "rsi": trim(rsi_data),
            "macd": trim(macd_data),
            "macd_signal": trim(macd_signal_data),
            "macd_hist": trim(macd_hist_data),
            "stoch_k": trim(stoch_k_data),
            "stoch_d": trim(stoch_d_data),
            "williams": trim(williams_data),
            "adx": trim(adx_data),
            "obv": trim(obv_data),
            "cmf": trim(cmf_data),
            "atr": trim(atr_data),
            "ao": trim(ao_data),
            "roc": trim(roc_data),
            "vortex_plus": trim(vortex_plus_data),
            "vortex_minus": trim(vortex_minus_data),
        },
        "price": round(df["Close"].iloc[-1], 2),
        "bars": len(trim(candles)),
    }

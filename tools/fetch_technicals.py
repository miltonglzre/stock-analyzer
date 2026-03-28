"""
fetch_technicals.py — Calculate technical indicators and support/resistance levels.

Indicators: RSI(14), SMA20/50/200, MACD(12,26,9), Bollinger Bands
Support/Resistance: Pivot highs/lows clustering + SMA confluence + 52w levels

Output: .tmp/{TICKER}_technicals.json

Usage:
    python tools/fetch_technicals.py AAPL
"""

import sys
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json, get_int

try:
    import pandas_ta as ta
    _HAS_TA = True
except ImportError:
    _HAS_TA = False
    print("[WARN] pandas-ta not installed. Install with: pip install pandas-ta")


# ── Indicator calculations (fallback if pandas-ta unavailable) ────────────────

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    if _HAS_TA:
        return ta.rsi(close, length=period)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    if _HAS_TA:
        result = ta.macd(close, fast=12, slow=26, signal=9)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            return result[cols[0]], result[cols[2]], result[cols[1]]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(close: pd.Series, period: int = 20) -> tuple[pd.Series, pd.Series, pd.Series]:
    if _HAS_TA:
        result = ta.bbands(close, length=period)
        if result is not None and not result.empty:
            cols = result.columns.tolist()
            return result[cols[0]], result[cols[2]], result[cols[1]]
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma - 2 * std, sma + 2 * std, sma


# ── Support / Resistance ──────────────────────────────────────────────────────

def _find_pivot_highs(high: pd.Series, window: int = 2) -> list[float]:
    pivots = []
    arr = high.values
    for i in range(window, len(arr) - window):
        if all(arr[i] >= arr[i - j] for j in range(1, window + 1)) and \
           all(arr[i] >= arr[i + j] for j in range(1, window + 1)):
            pivots.append(float(arr[i]))
    return pivots


def _find_pivot_lows(low: pd.Series, window: int = 2) -> list[float]:
    pivots = []
    arr = low.values
    for i in range(window, len(arr) - window):
        if all(arr[i] <= arr[i - j] for j in range(1, window + 1)) and \
           all(arr[i] <= arr[i + j] for j in range(1, window + 1)):
            pivots.append(float(arr[i]))
    return pivots


def _cluster_levels(levels: list[float], tolerance: float = 0.015) -> list[dict]:
    if not levels:
        return []
    sorted_levels = sorted(levels)
    clusters = []
    current_cluster = [sorted_levels[0]]

    for price in sorted_levels[1:]:
        if (price - current_cluster[0]) / current_cluster[0] <= tolerance:
            current_cluster.append(price)
        else:
            clusters.append(current_cluster)
            current_cluster = [price]
    clusters.append(current_cluster)

    result = []
    for cluster in clusters:
        center = round(sum(cluster) / len(cluster), 2)
        touches = len(cluster)
        strength = "strong" if touches >= 3 else "moderate"
        result.append({"price": center, "strength": strength, "touches": touches, "method": "pivot_cluster"})

    return sorted(result, key=lambda x: x["price"])


def _sma_confluence_levels(current_price: float, sma_values: dict) -> list[dict]:
    levels = []
    for name, value in sma_values.items():
        if value is None:
            continue
        if abs(current_price - value) / value <= 0.02:
            levels.append({"price": round(value, 2), "strength": "moderate", "touches": 1, "method": name})
    return levels


def _build_sr_levels(high: pd.Series, low: pd.Series, current_price: float, sma_values: dict,
                     w52_high: float, w52_low: float) -> tuple[list[dict], list[dict]]:
    pivot_highs = _find_pivot_highs(high)
    pivot_lows = _find_pivot_lows(low)

    resistance_candidates = [p for p in pivot_highs if p > current_price]
    support_candidates = [p for p in pivot_lows if p < current_price]

    resistance_levels = _cluster_levels(resistance_candidates)
    support_levels = _cluster_levels(support_candidates)

    # Add SMA confluence
    for lvl in _sma_confluence_levels(current_price, sma_values):
        if lvl["price"] > current_price:
            resistance_levels.append(lvl)
        else:
            support_levels.append(lvl)

    # Always include 52-week levels
    if w52_high and w52_high > current_price:
        resistance_levels.append({"price": round(w52_high, 2), "strength": "strong", "touches": 1, "method": "52w_high"})
    if w52_low and w52_low < current_price:
        support_levels.append({"price": round(w52_low, 2), "strength": "strong", "touches": 1, "method": "52w_low"})

    # Deduplicate by price proximity (within 0.5%)
    def dedup(lst):
        seen = []
        for item in sorted(lst, key=lambda x: x["price"]):
            if not seen or abs(item["price"] - seen[-1]["price"]) / seen[-1]["price"] > 0.005:
                seen.append(item)
        return seen

    return dedup(support_levels), dedup(resistance_levels)


# ── Trend detection ───────────────────────────────────────────────────────────

def _trend(close: pd.Series, sma20: float, sma50: float, sma200: float) -> dict:
    current = float(close.iloc[-1])
    short_term = "Bullish" if current > sma20 else "Bearish"
    long_term = "Bullish" if current > sma200 else "Bearish"

    golden_cross = sma50 > sma200 if sma50 and sma200 else None
    cross_label = "Golden Cross (Bullish)" if golden_cross else "Death Cross (Bearish)" if golden_cross is False else "N/A"

    return {
        "short_term":   short_term,
        "long_term":    long_term,
        "ma_cross":     cross_label,
        "above_sma20":  current > sma20 if sma20 else None,
        "above_sma50":  current > sma50 if sma50 else None,
        "above_sma200": current > sma200 if sma200 else None,
    }


# ── Technical score ────────────────────────────────────────────────────────────

def _technical_score(rsi_val: float, macd_val: float, signal_val: float,
                     trend: dict, current_price: float,
                     nearest_support: float | None, nearest_resistance: float | None) -> tuple[float, list[str], dict]:
    """
    Returns (score -1.0 to +1.0, reasons list, signals dict).
    """
    points = 0.0
    max_points = 0.0
    reasons = []
    signals = {}

    # ── RSI ───────────────────────────────────────────────────────────────────
    if rsi_val is not None and not np.isnan(rsi_val):
        max_points += 2
        if rsi_val < 30:
            points += 2
            reasons.append(f"RSI {rsi_val:.1f} — oversold, potential reversal up")
            signals["rsi_oversold"] = True
            signals["rsi_overbought"] = False
        elif rsi_val > 70:
            points -= 2
            reasons.append(f"RSI {rsi_val:.1f} — overbought, potential pullback")
            signals["rsi_oversold"] = False
            signals["rsi_overbought"] = True
        elif 40 <= rsi_val <= 60:
            points += 0
            reasons.append(f"RSI {rsi_val:.1f} — neutral momentum")
            signals["rsi_oversold"] = False
            signals["rsi_overbought"] = False
        elif rsi_val < 40:
            points += 0.5
            reasons.append(f"RSI {rsi_val:.1f} — slightly weak, watch for bounce")
            signals["rsi_oversold"] = False
            signals["rsi_overbought"] = False
        else:
            points -= 0.5
            reasons.append(f"RSI {rsi_val:.1f} — slightly strong, caution")
            signals["rsi_oversold"] = False
            signals["rsi_overbought"] = False

    # ── MACD ──────────────────────────────────────────────────────────────────
    if macd_val is not None and signal_val is not None:
        max_points += 2
        if macd_val > signal_val:
            points += 2
            reasons.append("MACD above signal line — bullish momentum")
            signals["macd_bullish"] = True
            signals["macd_bearish"] = False
        else:
            points -= 2
            reasons.append("MACD below signal line — bearish momentum")
            signals["macd_bullish"] = False
            signals["macd_bearish"] = True

    # ── Trend ─────────────────────────────────────────────────────────────────
    if trend.get("above_sma200") is not None:
        max_points += 2
        if trend["long_term"] == "Bullish":
            points += 2
            reasons.append("Price above SMA200 — long-term uptrend")
            signals["ma_golden_cross"] = trend.get("above_sma50", False) and trend.get("above_sma200", False)
            signals["ma_death_cross"] = False
        else:
            points -= 2
            reasons.append("Price below SMA200 — long-term downtrend")
            signals["ma_golden_cross"] = False
            signals["ma_death_cross"] = not (trend.get("above_sma50", True) or trend.get("above_sma200", True))

    if trend.get("above_sma50") is not None:
        max_points += 1
        if trend["short_term"] == "Bullish":
            points += 1
            reasons.append("Price above SMA20 — short-term uptrend")
        else:
            points -= 1
            reasons.append("Price below SMA20 — short-term downtrend")

    # ── Support proximity ─────────────────────────────────────────────────────
    if nearest_support and current_price:
        max_points += 1
        dist_pct = (current_price - nearest_support) / nearest_support * 100
        if 0 < dist_pct <= 3:
            points += 1
            reasons.append(f"Price near support ${nearest_support:.2f} ({dist_pct:.1f}% above)")
            signals["support_bounce"] = True
        else:
            signals["support_bounce"] = False

    if nearest_resistance and current_price:
        max_points += 1
        dist_pct = (nearest_resistance - current_price) / current_price * 100
        if 0 < dist_pct <= 3:
            points -= 1
            reasons.append(f"Price near resistance ${nearest_resistance:.2f} ({dist_pct:.1f}% below)")
            signals["resistance_hit"] = True
        else:
            signals["resistance_hit"] = False

    score = round(points / max_points, 4) if max_points > 0 else 0.0
    score = max(-1.0, min(1.0, score))
    return score, reasons, signals


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_technicals(ticker: str) -> dict:
    lookback = get_int("LOOKBACK_DAYS", 365)
    t = yf.Ticker(ticker)
    hist = t.history(period=f"{lookback}d", interval="1d")

    if hist.empty or len(hist) < 30:
        print(f"[ERROR] Insufficient price history for {ticker}")
        sys.exit(1)

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]
    current_price = float(close.iloc[-1])

    # ── Moving averages ───────────────────────────────────────────────────────
    def sma_val(n):
        s = close.rolling(n).mean()
        v = s.iloc[-1] if len(s) >= n else None
        return round(float(v), 2) if v and not np.isnan(v) else None

    sma20 = sma_val(20)
    sma50 = sma_val(50)
    sma200 = sma_val(200)

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_series = _rsi(close)
    rsi_val = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else None
    if rsi_val and np.isnan(rsi_val):
        rsi_val = None

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_line, signal_line, histogram = _macd(close)
    macd_val = float(macd_line.iloc[-1]) if macd_line is not None and not macd_line.empty else None
    signal_val = float(signal_line.iloc[-1]) if signal_line is not None and not signal_line.empty else None
    hist_val = float(histogram.iloc[-1]) if histogram is not None and not histogram.empty else None

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_lower, bb_upper, bb_mid = _bollinger(close)
    bb_lower_val = round(float(bb_lower.iloc[-1]), 2) if bb_lower is not None else None
    bb_upper_val = round(float(bb_upper.iloc[-1]), 2) if bb_upper is not None else None
    bb_mid_val = round(float(bb_mid.iloc[-1]), 2) if bb_mid is not None else None

    # ── Support / Resistance ──────────────────────────────────────────────────
    info = t.info
    w52_high = info.get("fiftyTwoWeekHigh")
    w52_low = info.get("fiftyTwoWeekLow")

    sma_values = {"sma20": sma20, "sma50": sma50, "sma200": sma200}
    support_levels, resistance_levels = _build_sr_levels(high, low, current_price, sma_values, w52_high, w52_low)

    nearest_support = support_levels[-1]["price"] if support_levels else None
    nearest_resistance = resistance_levels[0]["price"] if resistance_levels else None

    # ── Trend ─────────────────────────────────────────────────────────────────
    trend = _trend(close, sma20, sma50, sma200)

    # ── Volume analysis ───────────────────────────────────────────────────────
    avg_volume_20 = float(volume.rolling(20).mean().iloc[-1])
    last_volume = float(volume.iloc[-1])
    volume_ratio = round(last_volume / avg_volume_20, 2) if avg_volume_20 > 0 else None

    # ── Score ─────────────────────────────────────────────────────────────────
    score, reasons, signals = _technical_score(
        rsi_val, macd_val, signal_val, trend, current_price, nearest_support, nearest_resistance
    )

    # ── Entry / Exit zones ────────────────────────────────────────────────────
    if nearest_support:
        entry_zone_low = round(nearest_support, 2)
        entry_zone_high = round(nearest_support * 1.015, 2)
        stop_loss = round(nearest_support * 0.97, 2)
    else:
        entry_zone_low = round(current_price * 0.97, 2)
        entry_zone_high = round(current_price, 2)
        stop_loss = round(current_price * 0.94, 2)

    target = round(nearest_resistance, 2) if nearest_resistance else round(current_price * 1.10, 2)

    data = {
        "ticker":           ticker.upper(),
        "current_price":    round(current_price, 2),
        "sma20":            sma20,
        "sma50":            sma50,
        "sma200":           sma200,
        "rsi":              round(rsi_val, 2) if rsi_val else None,
        "macd":             round(macd_val, 4) if macd_val else None,
        "macd_signal":      round(signal_val, 4) if signal_val else None,
        "macd_histogram":   round(hist_val, 4) if hist_val else None,
        "bb_lower":         bb_lower_val,
        "bb_upper":         bb_upper_val,
        "bb_mid":           bb_mid_val,
        "volume_last":      int(last_volume),
        "volume_avg_20d":   int(avg_volume_20),
        "volume_ratio":     volume_ratio,
        "trend":            trend,
        "support_levels":   support_levels,
        "resistance_levels": resistance_levels,
        "nearest_support":  nearest_support,
        "nearest_resistance": nearest_resistance,
        "entry_zone_low":   entry_zone_low,
        "entry_zone_high":  entry_zone_high,
        "stop_loss":        stop_loss,
        "target_price":     target,
        "score":            score,
        "signals":          signals,
        "reasoning":        reasons,
    }

    path = tmp_path(ticker, "technicals")
    save_json(path, data)
    rsi_str = f"{rsi_val:.1f}" if rsi_val else "N/A"
    print(f"[OK] Technicals (score={score:.2f}, RSI={rsi_str}) saved -> {path}")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_technicals.py <TICKER>")
        sys.exit(1)
    fetch_technicals(sys.argv[1].upper())

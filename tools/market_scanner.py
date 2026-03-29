"""
market_scanner.py — Scan the watchlist and rank trading opportunities.

Strategy (2-stage):
  Stage 1: Batch-download all tickers in one yfinance call (~20 sec for 75 tickers)
  Stage 2: Quick-score each ticker using price, volume, RSI, MA trend, momentum
  Result:  Top buys + top sells ranked by score, with manipulation flags

Cache: .tmp/scanner_cache.json  (valid 15 min by default)

Usage:
    python tools/market_scanner.py              # uses cache if fresh
    python tools/market_scanner.py --force      # force rescan
    python tools/market_scanner.py --top 5      # show top 5 each side
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_json, save_json
from market_hours import get_market_status
from watchlist import ALL_TICKERS, WATCHLIST, TICKER_SECTOR
from detect_manipulation import detect_manipulation

_ROOT = Path(__file__).parent.parent
CACHE_FILE = _ROOT / ".tmp" / "scanner_cache.json"
CACHE_TTL_MINUTES = 15

# ── Day-of-week seasonality ────────────────────────────────────────────────────
# Based on documented "day-of-week effect" in US equities research.
# These are small nudges — never override a strong signal, only break ties.
_DOW_DATA = {
    0: {"name": "Monday",    "adj": -0.05, "bias": "bearish",
        "note": "Monday Effect — weekend news digestion, institutional repositioning often pressures opens"},
    1: {"name": "Tuesday",   "adj": +0.02, "bias": "neutral",
        "note": "Typical recovery day — dip buyers often step in after Monday weakness"},
    2: {"name": "Wednesday", "adj": +0.03, "bias": "neutral",
        "note": "Mid-week is historically the most active and liquid session"},
    3: {"name": "Thursday",  "adj": +0.04, "bias": "bullish",
        "note": "Pre-weekend institutional buying tends to start Thursday afternoon"},
    4: {"name": "Friday",    "adj": +0.01, "bias": "neutral",
        "note": "Window dressing and short-covering can push prices up, but volume fades late"},
}


_DOW_NAMES_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}

def get_dow_context() -> dict:
    """Return today's day-of-week seasonality context."""
    today = datetime.now()
    dow   = today.weekday()   # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    real_name = today.strftime("%A")  # nombre real del día
    # For market seasonality data, use Friday on weekends
    market_dow = min(dow, 4)
    d = _DOW_DATA[market_dow]
    return {
        "weekday":    dow,
        "name":       _DOW_NAMES_ES.get(real_name, real_name),
        "name_en":    real_name,
        "is_weekend": dow >= 5,
        "adj":        d["adj"],
        "bias":       d["bias"],
        "note":       d["note"],
    }


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_is_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        return (datetime.now() - cached_at) < timedelta(minutes=CACHE_TTL_MINUTES)
    except Exception:
        return False


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


# ── Quick scoring ──────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - (100 / (1 + rs))
    val   = rsi.iloc[-1]
    return round(float(val), 1) if pd.notna(val) else 50.0


def _quick_score(hist: pd.DataFrame) -> dict:
    """
    Score a ticker -1..+1 using only OHLCV data.
    Fast and deterministic — no API calls needed beyond the batch download.
    """
    if hist is None or len(hist) < 10:
        return {"score": 0.0, "signals": {}, "rsi": 50.0,
                "change_1d_pct": 0.0, "change_5d_pct": 0.0,
                "current_price": 0.0, "sma20": None, "sma50": None,
                "volume_ratio": None}

    close  = hist["Close"].dropna()
    volume = hist["Volume"].dropna()

    if len(close) < 5:
        return {"score": 0.0, "signals": {}, "rsi": 50.0,
                "change_1d_pct": 0.0, "change_5d_pct": 0.0,
                "current_price": float(close.iloc[-1]) if len(close) else 0.0,
                "sma20": None, "sma50": None, "volume_ratio": None}

    score   = 0.0
    signals = {}

    # RSI
    rsi = _rsi(close)
    if rsi < 30:
        score += 0.35; signals["rsi_oversold"] = True
    elif rsi < 40:
        score += 0.15
    elif rsi > 70:
        score -= 0.35; signals["rsi_overbought"] = True
    elif rsi > 60:
        score -= 0.15

    # Moving average alignment
    n20  = min(20, len(close))
    n50  = min(50, len(close))
    sma20 = float(close.rolling(n20).mean().iloc[-1])
    sma50 = float(close.rolling(n50).mean().iloc[-1])
    curr  = float(close.iloc[-1])

    if curr > sma20 and sma20 > sma50:
        score += 0.20; signals["above_both_mas"] = True
    elif curr < sma20 and sma20 < sma50:
        score -= 0.20; signals["below_both_mas"] = True

    # Golden / death cross (last 5 days)
    if len(close) >= 55:
        sma20_prev = float(close.rolling(20).mean().iloc[-6])
        sma50_prev = float(close.rolling(50).mean().iloc[-6])
        if sma20_prev < sma50_prev and sma20 > sma50:
            score += 0.25; signals["golden_cross"] = True
        elif sma20_prev > sma50_prev and sma20 < sma50:
            score -= 0.25; signals["death_cross"] = True

    # 5-day momentum
    if len(close) >= 6:
        mom5 = (curr - float(close.iloc[-6])) / float(close.iloc[-6])
        score += round(min(0.20, max(-0.20, mom5 * 2.5)), 4)
        if mom5 > 0.05:
            signals["strong_momentum_up"] = True
        elif mom5 < -0.05:
            signals["strong_momentum_down"] = True

    # Volume confirmation
    avg_vol = float(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else float(volume.mean())
    curr_vol = float(volume.iloc[-1])
    vol_ratio = (curr_vol / avg_vol) if avg_vol and avg_vol > 0 else 1.0

    if len(close) >= 2:
        day_chg = (curr - float(close.iloc[-2])) / float(close.iloc[-2])
        if vol_ratio >= 2:
            if day_chg > 0:
                score += 0.10; signals["volume_confirms_up"] = True
            elif day_chg < 0:
                score -= 0.10; signals["volume_confirms_down"] = True

    # Price % changes
    chg_1d = ((curr - float(close.iloc[-2])) / float(close.iloc[-2]) * 100) if len(close) >= 2 else 0.0
    chg_5d = ((curr - float(close.iloc[-6])) / float(close.iloc[-6]) * 100) if len(close) >= 6 else 0.0

    return {
        "score":         round(max(-1.0, min(1.0, score)), 4),
        "signals":       signals,
        "rsi":           rsi,
        "change_1d_pct": round(chg_1d, 2),
        "change_5d_pct": round(chg_5d, 2),
        "current_price": round(curr, 2),
        "sma20":         round(sma20, 2),
        "sma50":         round(sma50, 2),
        "volume_ratio":  round(vol_ratio, 2),
    }


# ── Main scan ──────────────────────────────────────────────────────────────────

def scan_market(force: bool = False, top_n: int = 10) -> dict:
    """
    Scan the full watchlist and return ranked opportunities.

    Returns a dict with:
      cached_at, market_status, total_scanned,
      top_buys, top_sells, manipulation_alerts, all_results
    """
    if not force and _cache_is_fresh():
        return _load_cache()

    market = get_market_status()

    # ── Stage 1: batch download ────────────────────────────────────────────────
    print(f"[Scanner] Downloading {len(ALL_TICKERS)} tickers...", flush=True)
    try:
        raw = yf.download(
            tickers=ALL_TICKERS,
            period="3mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return {
            "error": str(e),
            "cached_at": datetime.now().isoformat(),
            "market_status": {
                "is_open": market["is_open"],
                "status":  market["status"],
                "message": market["message"],
            },
            "total_scanned": 0,
            "top_buys": [], "top_sells": [],
            "manipulation_alerts": [], "all_results": [],
        }

    # ── Stage 2: score each ticker ─────────────────────────────────────────────
    results            = []
    manipulation_alerts = []
    dow_ctx            = get_dow_context()
    dow_adj            = dow_ctx["adj"]   # small score nudge based on day of week

    for ticker in ALL_TICKERS:
        try:
            # Extract this ticker's slice from the batch DataFrame
            if len(ALL_TICKERS) == 1:
                hist = raw
            elif ticker in raw.columns.get_level_values(0):
                hist = raw[ticker].dropna(how="all")
            else:
                continue

            if hist is None or len(hist) < 10:
                continue

            scored = _quick_score(hist)
            manip_flags = detect_manipulation(ticker, hist, info={})  # price/vol only

            sector = TICKER_SECTOR.get(ticker, "Other")

            # Apply day-of-week adjustment (capped so it never flips a strong signal)
            raw_score = scored["score"]
            s = round(max(-1.0, min(1.0, raw_score + dow_adj)), 4)

            # Recommendation
            if s >= 0.15:
                rec = "Buy"
            elif s <= -0.15:
                rec = "Sell"
            else:
                rec = "Wait"

            result = {
                "ticker":         ticker,
                "sector":         sector,
                "score":          s,
                "recommendation": rec,
                "rsi":            scored["rsi"],
                "current_price":  scored["current_price"],
                "change_1d_pct":  scored["change_1d_pct"],
                "change_5d_pct":  scored["change_5d_pct"],
                "volume_ratio":   scored["volume_ratio"],
                "sma20":          scored["sma20"],
                "sma50":          scored["sma50"],
                "signals":        scored["signals"],
                "manipulation_flags": manip_flags,
                "confidence_pct": min(100, int(abs(s) * 100 + 20)),
            }
            results.append(result)

            # Collect alerts
            for flag in manip_flags:
                if flag["severity"] in ("high", "medium"):
                    manipulation_alerts.append({"ticker": ticker, "sector": sector, **flag})

        except Exception:
            continue

    # ── Rank ───────────────────────────────────────────────────────────────────
    top_buys  = sorted(
        [r for r in results if r["recommendation"] == "Buy"],
        key=lambda x: x["score"], reverse=True,
    )[:top_n]

    top_sells = sorted(
        [r for r in results if r["recommendation"] == "Sell"],
        key=lambda x: x["score"],
    )[:top_n]

    sev_order = {"high": 0, "medium": 1, "low": 2}
    manipulation_alerts.sort(key=lambda x: sev_order.get(x["severity"], 3))

    output = {
        "cached_at": datetime.now().isoformat(),
        "market_status": {
            "is_open": market["is_open"],
            "status":  market["status"],
            "message": market["message"],
        },
        "dow_context":          dow_ctx,
        "total_scanned":        len(results),
        "top_buys":             top_buys,
        "top_sells":            top_sells,
        "manipulation_alerts":  manipulation_alerts[:20],
        "all_results":          sorted(results, key=lambda x: x["score"], reverse=True),
    }

    _save_cache(output)
    print(f"[Scanner] Done — {len(results)} tickers scored.", flush=True)
    return output


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan watchlist for opportunities")
    parser.add_argument("--force", action="store_true", help="Ignore cache, force rescan")
    parser.add_argument("--top",   type=int, default=5, help="Show top N each side")
    args = parser.parse_args()

    print("Scanning market... may take 30-60 seconds on first run")
    data = scan_market(force=args.force, top_n=args.top)

    if "error" in data:
        print(f"Error: {data['error']}")
        sys.exit(1)

    mkt = data["market_status"]
    print(f"\nMarket  : {mkt['message']}")
    print(f"Scanned : {data['total_scanned']} tickers")
    print(f"Cached  : {data['cached_at'][:16]}")

    print("\n--- TOP BUYS ---")
    for r in data["top_buys"]:
        flags = "  [!]" if r["manipulation_flags"] else ""
        print(f"  {r['ticker']:6s}  score={r['score']:+.3f}  RSI={r['rsi']:4.0f}"
              f"  {r['change_1d_pct']:+5.1f}%/day  vol={r['volume_ratio']:.1f}x{flags}")

    print("\n--- TOP SELLS ---")
    for r in data["top_sells"]:
        flags = "  [!]" if r["manipulation_flags"] else ""
        print(f"  {r['ticker']:6s}  score={r['score']:+.3f}  RSI={r['rsi']:4.0f}"
              f"  {r['change_1d_pct']:+5.1f}%/day  vol={r['volume_ratio']:.1f}x{flags}")

    alerts = data.get("manipulation_alerts", [])
    if alerts:
        print(f"\n--- MANIPULATION ALERTS ({len(alerts)}) ---")
        for a in alerts[:8]:
            print(f"  [{a['severity'].upper():6s}] {a['ticker']}: {a['detail']}")

"""
fetch_fear_greed.py — Fetch the CNN Fear & Greed Index (stock market sentiment).

Source: CNN's unofficial public endpoint — free, no API key required.
Fallback: compute a proxy from VIX + S&P 500 momentum via yfinance.

Cache: .tmp/fear_greed.json (valid 60 minutes — index updates once per day)

Usage:
    python tools/fetch_fear_greed.py
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from utils import save_json, load_json, tmp_path

_ROOT      = Path(__file__).parent.parent
_CACHE     = _ROOT / ".tmp" / "fear_greed.json"
_CNN_URL   = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
_TTL_MIN   = 60   # refresh every hour (index updates ~daily)


# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_fresh() -> bool:
    if not _CACHE.exists():
        return False
    try:
        data = json.loads(_CACHE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        return (datetime.now() - cached_at) < timedelta(minutes=_TTL_MIN)
    except Exception:
        return False


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict):
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


# ── Rating helpers ─────────────────────────────────────────────────────────────

def _rating(score: float) -> str:
    if score <= 25:   return "Extreme Fear"
    if score <= 44:   return "Fear"
    if score <= 55:   return "Neutral"
    if score <= 75:   return "Greed"
    return "Extreme Greed"


def _color(rating: str) -> str:
    return {
        "Extreme Fear": "#ef5350",
        "Fear":         "#f39c12",
        "Neutral":      "#aaaaaa",
        "Greed":        "#00d4aa",
        "Extreme Greed":"#00ff88",
    }.get(rating, "#aaa")


def _trading_bias(score: float) -> dict:
    """
    Contrarian interpretation of Fear & Greed for trading decisions.
    Extreme Fear → historically a good time to buy.
    Extreme Greed → historically a good time to reduce exposure.
    """
    if score <= 25:
        return {
            "signal":  "contrarian_buy",
            "note":    "Extreme Fear — market oversold. Historically a good time to accumulate.",
            "score_adj": +0.06,   # small boost to Buy scores
        }
    if score <= 44:
        return {
            "signal":  "caution",
            "note":    "Fear present — be selective, stick to high-conviction picks only.",
            "score_adj": +0.02,
        }
    if score <= 55:
        return {
            "signal":  "neutral",
            "note":    "Market sentiment is balanced — follow individual stock signals.",
            "score_adj": 0.0,
        }
    if score <= 75:
        return {
            "signal":  "caution_greed",
            "note":    "Greed rising — market may be getting extended. Tighten stops.",
            "score_adj": -0.02,
        }
    return {
        "signal":  "contrarian_sell",
        "note":    "Extreme Greed — market frothy. High risk of reversal. Reduce new positions.",
        "score_adj": -0.06,
    }


# ── CNN fetcher ────────────────────────────────────────────────────────────────

def _fetch_cnn() -> dict | None:
    try:
        resp = requests.get(_CNN_URL, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        fg   = data.get("fear_and_greed", {})
        score = float(fg.get("score", 0))
        if not (0 <= score <= 100):
            return None
        rating = fg.get("rating") or _rating(score)
        return {
            "score":          round(score, 1),
            "rating":         rating,
            "color":          _color(rating),
            "prev_close":     round(float(fg.get("previous_close",  score)), 1),
            "prev_week":      round(float(fg.get("previous_1_week", score)), 1),
            "prev_month":     round(float(fg.get("previous_1_month",score)), 1),
            "source":         "CNN Fear & Greed Index",
        }
    except Exception as e:
        print(f"[FearGreed] CNN fetch failed: {e}")
        return None


# ── VIX-based fallback ─────────────────────────────────────────────────────────

def _fetch_vix_proxy() -> dict | None:
    """
    Compute a rough F&G proxy from VIX + S&P 500 momentum.
    VIX > 30 → Fear, VIX < 15 → Greed.
    """
    try:
        import yfinance as yf
        vix_data = yf.download("^VIX ^GSPC", period="20d", interval="1d",
                               auto_adjust=True, progress=False)
        vix_close  = vix_data["Close"]["^VIX"].dropna()
        sp_close   = vix_data["Close"]["^GSPC"].dropna()

        if vix_close.empty:
            return None

        vix  = float(vix_close.iloc[-1])
        # Map VIX to 0-100 inverted (high VIX = fear = low score)
        # VIX range ~10-50: score = 100 - ((vix - 10) / 40) * 100
        vix_score = max(0, min(100, 100 - ((vix - 10) / 40) * 100))

        # Momentum: S&P 500 20-day return
        if len(sp_close) >= 10:
            mom = (float(sp_close.iloc[-1]) - float(sp_close.iloc[-10])) / float(sp_close.iloc[-10])
            mom_score = min(100, max(0, 50 + mom * 500))  # ±10% → maps to 0-100
        else:
            mom_score = 50

        score  = round((vix_score * 0.6 + mom_score * 0.4), 1)
        rating = _rating(score)

        return {
            "score":      score,
            "rating":     rating,
            "color":      _color(rating),
            "prev_close": score,
            "prev_week":  score,
            "prev_month": score,
            "source":     f"VIX proxy (VIX={vix:.1f})",
        }
    except Exception as e:
        print(f"[FearGreed] VIX fallback failed: {e}")
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_fear_greed(force: bool = False) -> dict:
    """
    Return the current Fear & Greed data.
    Tries CNN first, falls back to VIX proxy.
    Returns a dict with: score, rating, color, prev_close, prev_week, prev_month,
                         source, bias (trading_bias dict), cached_at.
    """
    if not force and _cache_fresh():
        return _load_cache()

    result = _fetch_cnn() or _fetch_vix_proxy()

    if result is None:
        result = {
            "score":      50.0,
            "rating":     "Neutral",
            "color":      "#aaa",
            "prev_close": 50.0,
            "prev_week":  50.0,
            "prev_month": 50.0,
            "source":     "unavailable",
        }

    result["bias"]      = _trading_bias(result["score"])
    result["cached_at"] = datetime.now().isoformat()

    _save_cache(result)
    return result


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    data = fetch_fear_greed(force=args.force)
    score  = data["score"]
    rating = data["rating"]
    bias   = data["bias"]

    print(f"\nFear & Greed Index: {score:.0f}/100 — {rating}")
    print(f"Source:   {data['source']}")
    print(f"Signal:   {bias['signal']}")
    print(f"Note:     {bias['note']}")
    print(f"Prev close: {data['prev_close']} | Prev week: {data['prev_week']} | Prev month: {data['prev_month']}")
    print(f"Score adj for scanner: {bias['score_adj']:+.2f}")

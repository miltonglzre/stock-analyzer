"""
volatile_scanner.py — Scan the volatile universe for unusual movers with news catalysts.

Uses a single yf.download() batch call (like market_scanner.py) to minimize API hits.
Scores each ticker on: volume spike, price momentum, news catalyst, and squeeze potential.

Usage:
    python tools/volatile_scanner.py
    python tools/volatile_scanner.py --force   # bypass cache
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json, load_json

# ── Constants ──────────────────────────────────────────────────────────────────

CACHE_FILE_NAME     = "volatile_scanner_cache"
CACHE_TTL_MINUTES   = 30
MIN_VOLUME_RATIO    = 2.5   # must be >= 2.5x average volume
MIN_PRICE_CHANGE    = 3.0   # must move >= 3% intraday
CATALYST_THRESHOLD  = 0.40  # minimum catalyst_score to be flagged
TOP_N               = 10

CATALYST_EVENTS = {
    "earnings_beat", "earnings_miss", "acquisition", "guidance_raise",
    "guidance_cut", "analyst_upgrade", "analyst_downgrade",
}


# ── Catalyst scoring ───────────────────────────────────────────────────────────

def _catalyst_score(volume_ratio: float, price_change_pct: float,
                    sentiment_score: float, events: list,
                    rsi_2d_ago: float | None) -> float:
    """
    Composite catalyst score [0.0 – 1.0].

    Weights:
      Volume spike  35%  (3x=0.0 baseline, 10x=1.0)
      Price move    35%  (3%=0.15, 20%=1.0)
      News          30%  (|sentiment| × event multiplier)
    Bonus: +0.15 squeeze setup if volume>=5x + green + was oversold
    """
    vol_component = min(1.0, max(0.0, (volume_ratio - 3.0) / 7.0))
    price_component = min(1.0, abs(price_change_pct) / 20.0)

    event_multiplier = 1.5 if any(e in CATALYST_EVENTS for e in (events or [])) else 1.0
    news_component = min(1.0, abs(sentiment_score) * event_multiplier)

    score = vol_component * 0.35 + price_component * 0.35 + news_component * 0.30

    # Squeeze bonus: high volume + green + was oversold
    if (volume_ratio >= 5.0 and price_change_pct > 0
            and rsi_2d_ago is not None and rsi_2d_ago < 35):
        score += 0.15

    return round(min(1.0, score), 4)


def _rsi(close, period: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


# ── News fetch (reuses Google RSS approach from fetch_news.py) ────────────────

def _quick_news(ticker: str, company_name: str = "") -> dict:
    """Light news fetch: return sentiment_score and key_events list."""
    # Check .tmp cache first
    path = tmp_path(ticker, "news")
    if path.exists():
        age = datetime.now().timestamp() - path.stat().st_mtime
        if age < 7200:  # 2-hour cache
            cached = load_json(path)
            return {
                "sentiment_score": cached.get("sentiment_score", 0.0),
                "events": cached.get("key_events", []),
                "headline": (cached.get("top_positive_headlines") or
                             cached.get("top_negative_headlines") or [""])[0],
            }

    try:
        import feedparser
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()

        query = f"{ticker}+stock"
        if company_name:
            query += f"+{company_name.replace(' ', '+')}"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        entries = feed.entries[:10]

        scores = []
        events = []
        headline = ""
        event_kw = {
            "earnings_beat": ["beat", "surpass", "exceed", "top estimates"],
            "earnings_miss": ["miss", "disappoint", "below estimates"],
            "acquisition":   ["acqui", "merger", "takeover", "buyout"],
            "guidance_raise":["raise guidance", "raise forecast", "upside"],
            "guidance_cut":  ["cut guidance", "lower forecast", "downside"],
            "analyst_upgrade":["upgrade", "buy rating", "overweight"],
            "analyst_downgrade":["downgrade", "sell rating", "underweight"],
            "fda":           ["fda", "approval", "clearance", "breakthrough"],
        }
        for entry in entries:
            text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
            score = sia.polarity_scores(text)["compound"]
            scores.append(score)
            if not headline and entry.get("title"):
                headline = entry["title"]
            for ev, kws in event_kw.items():
                if any(kw in text for kw in kws) and ev not in events:
                    events.append(ev)

        avg = sum(scores) / len(scores) if scores else 0.0
        return {"sentiment_score": round(avg, 4), "events": events, "headline": headline}
    except Exception:
        return {"sentiment_score": 0.0, "events": [], "headline": ""}


# ── Main scanner ───────────────────────────────────────────────────────────────

def scan_volatile_market(force: bool = False, top_n: int = TOP_N) -> dict:
    """
    Scan the volatile universe for unusual movers.
    Returns a dict with top opportunities sorted by catalyst_score.
    Uses a 30-minute file cache.
    """
    from volatile_watchlist import VOLATILE_TICKERS, VOLATILE_SECTOR

    # ── Cache check ────────────────────────────────────────────────────────────
    cache_path = tmp_path("volatile", "scanner_cache")
    if not force and cache_path.exists():
        cached = load_json(cache_path)
        cached_at = cached.get("cached_at", "")
        if cached_at:
            age = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds()
            if age < CACHE_TTL_MINUTES * 60:
                return cached

    # ── Batch download ─────────────────────────────────────────────────────────
    import yfinance as yf
    try:
        raw = yf.download(
            tickers=VOLATILE_TICKERS,
            period="1mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return {"error": str(e), "cached_at": datetime.now().isoformat(), "opportunities": []}

    results = []

    for ticker in VOLATILE_TICKERS:
        try:
            # Extract this ticker's slice
            if len(VOLATILE_TICKERS) == 1:
                hist = raw
            else:
                if ticker not in raw.columns.get_level_values(1):
                    continue
                hist = raw.xs(ticker, axis=1, level=1).dropna(how="all")

            if hist is None or len(hist) < 5:
                continue

            close  = hist["Close"].dropna()
            volume = hist["Volume"].dropna()
            if len(close) < 3 or len(volume) < 3:
                continue

            today_close = float(close.iloc[-1])
            prev_close  = float(close.iloc[-2])
            today_vol   = float(volume.iloc[-1])
            avg_vol     = float(volume.iloc[:-1].mean())

            if avg_vol <= 0 or today_close <= 0:
                continue

            price_change_pct = (today_close - prev_close) / prev_close * 100
            volume_ratio     = today_vol / avg_vol

            # Gate 1 + 2: must pass volume AND price threshold
            if volume_ratio < MIN_VOLUME_RATIO or abs(price_change_pct) < MIN_PRICE_CHANGE:
                continue

            # RSI 2 days ago for squeeze detection
            rsi_series = _rsi(close)
            rsi_2d_ago = float(rsi_series.iloc[-3]) if len(rsi_series) >= 3 else None
            rsi_now    = float(rsi_series.iloc[-1]) if len(rsi_series) >= 1 else None

            # Gate 3: news / catalyst
            news = _quick_news(ticker)
            sentiment = news["sentiment_score"]
            events    = news["events"]
            headline  = news["headline"]

            score = _catalyst_score(volume_ratio, price_change_pct,
                                    sentiment, events, rsi_2d_ago)

            if score < CATALYST_THRESHOLD:
                continue

            results.append({
                "ticker":          ticker,
                "sector":          VOLATILE_SECTOR.get(ticker, "Unknown"),
                "price":           round(today_close, 2),
                "change_pct":      round(price_change_pct, 2),
                "volume_ratio":    round(volume_ratio, 1),
                "rsi":             round(rsi_now, 1) if rsi_now else None,
                "catalyst_score":  score,
                "sentiment_score": sentiment,
                "events":          events,
                "headline":        headline[:120] if headline else "",
                "direction":       "up" if price_change_pct > 0 else "down",
            })

        except Exception:
            continue

    # Sort by catalyst_score descending
    results.sort(key=lambda x: -x["catalyst_score"])

    output = {
        "cached_at":    datetime.now().isoformat(),
        "total_scanned": len(VOLATILE_TICKERS),
        "opportunities": results[:top_n],
        "all_results":   results,
    }
    save_json(cache_path, output)
    print(f"[OK] Volatile scan: {len(results)} opportunities from {len(VOLATILE_TICKERS)} tickers")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan volatile universe for movers")
    parser.add_argument("--force", action="store_true", help="Bypass cache")
    parser.add_argument("--top",   type=int, default=10, help="Top N results")
    args = parser.parse_args()
    data = scan_volatile_market(force=args.force, top_n=args.top)
    for opp in data.get("opportunities", []):
        print(f"{opp['ticker']:6s} {opp['change_pct']:+.1f}% "
              f"vol={opp['volume_ratio']:.1f}x score={opp['catalyst_score']:.2f} "
              f"| {opp['headline'][:60]}")

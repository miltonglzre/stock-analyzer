"""
intraday_scanner.py — Real-time intraday mover detection.

Unlike volatile_scanner.py (daily candles), this uses 5-minute candles
to catch moves AS THEY START — not after the day closes.

How it works:
  1. Downloads 5-min candles for today for all volatile tickers (one batch call)
  2. Also extracts tickers from breaking news headlines (catches stocks NOT in watchlist)
  3. Detects: price move from prev close, intraday volume spike, move phase
  4. Scores urgency: early-phase high-volume moves with news = strongest alerts
  5. Provides sell signals for active positions

Move phases:
  early    (<45 min since spike)  — best entry risk/reward
  active   (45–120 min)          — still valid, expect more volatility
  extended (>120 min)            — likely extended, risky entry

Cache: 5 minutes (vs 30 min for daily scanner)

Usage:
    python tools/intraday_scanner.py
    python tools/intraday_scanner.py --force
"""

import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, date

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json, load_json

# ── Constants ──────────────────────────────────────────────────────────────────

CACHE_FILE       = "intraday_scanner_cache"
CACHE_TTL_MIN    = 5          # refresh every 5 minutes
MIN_PRICE_MOVE   = 2.0        # % move from prev close to qualify
MIN_VOL_SPIKE    = 3.0        # recent candle must be Nx avg 5-min volume
ALERT_THRESHOLD  = 0.35       # minimum alert score to surface
TOP_N            = 8

# Common words to exclude when parsing tickers from news headlines
_NOT_TICKERS = {
    "A", "AN", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT",
    "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE", "AM", "PM",
    "AS", "AT", "CEO", "CFO", "COO", "IPO", "ETF", "SEC", "FDA", "IRS",
    "THE", "AND", "BUT", "FOR", "NOT", "NEW", "NOW", "ALL", "TOP", "BIG",
    "CUT", "RUN", "OUT", "OFF", "HIT", "SET", "GET", "PUT", "MAY", "CAN",
    "LAW", "TAX", "WAR", "OIL", "GDP", "FED", "AI", "EV",
}


# ── News ticker extraction ─────────────────────────────────────────────────────

def _extract_news_tickers(max_articles: int = 30) -> list[dict]:
    """
    Fetch breaking market news and extract potential ticker symbols.
    Returns list of {ticker, headline, source}.
    """
    try:
        import feedparser
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()

        feeds = [
            "https://news.google.com/rss/search?q=stock+earnings+beat+miss&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=FDA+approval+drug+stock&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=acquisition+merger+buyout+stock&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=short+squeeze+stock+surge&hl=en-US&gl=US&ceid=US:en",
        ]

        seen_tickers: set = set()
        results: list[dict] = []

        for url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:max_articles // len(feeds) + 2]:
                    title = entry.get("title", "")
                    # Extract ALL-CAPS 2-5 letter words (likely tickers)
                    tokens = re.findall(r'\b([A-Z]{2,5})\b', title)
                    candidates = [t for t in tokens if t not in _NOT_TICKERS]
                    sentiment = sia.polarity_scores(title)["compound"]
                    pub = entry.get("published", "")
                    for tk in candidates:
                        if tk not in seen_tickers:
                            seen_tickers.add(tk)
                            results.append({
                                "ticker":    tk,
                                "headline":  title[:120],
                                "sentiment": sentiment,
                                "published": pub,
                                "source":    "news_extracted",
                            })
            except Exception:
                continue

        return results
    except Exception:
        return []


# ── RSI helper ────────────────────────────────────────────────────────────────

def _rsi(series, period: int = 3) -> float:
    """Short-period RSI for overbought/oversold detection on 5-min candles."""
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


# ── Phase detection ───────────────────────────────────────────────────────────

def _detect_phase(candles, spike_start_idx: int) -> tuple[str, int]:
    """
    Determine how far into the move we are.
    Returns (phase_label, minutes_since_spike).
    """
    if spike_start_idx < 0 or spike_start_idx >= len(candles):
        return "unknown", 0

    try:
        spike_time   = candles.index[spike_start_idx]
        current_time = candles.index[-1]
        # Handle timezone-aware/naive
        if hasattr(spike_time, "tzinfo") and spike_time.tzinfo:
            from datetime import timezone
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()
        elapsed_min = int((current_time - spike_time).total_seconds() / 60)
    except Exception:
        elapsed_min = 0

    if elapsed_min <= 45:
        return "early", elapsed_min
    elif elapsed_min <= 120:
        return "active", elapsed_min
    else:
        return "extended", elapsed_min


# ── Alert score ───────────────────────────────────────────────────────────────

def _alert_score(price_move_pct: float, vol_spike: float,
                 sentiment: float, phase: str, has_news: bool) -> float:
    """
    Urgency score [0–1].
    Higher = stronger signal to act NOW.
    """
    try:
        from volatile_learning import load_volatile_weights
        w = load_volatile_weights()
    except Exception:
        w = {"w_volume": 0.35, "w_price": 0.35, "w_news": 0.30}

    price_c  = min(1.0, abs(price_move_pct) / 15.0)
    vol_c    = min(1.0, max(0.0, (vol_spike - 2.0) / 8.0))
    news_c   = min(1.0, abs(sentiment) * (1.5 if has_news else 0.8))

    score = vol_c * w["w_volume"] + price_c * w["w_price"] + news_c * w["w_news"]

    # Phase multipliers — early moves score higher
    phase_mult = {"early": 1.2, "active": 1.0, "extended": 0.65, "unknown": 0.8}
    score *= phase_mult.get(phase, 1.0)

    return round(min(1.0, score), 4)


# ── Sell signal analysis ───────────────────────────────────────────────────────

def get_sell_signals(ticker: str, entry_price: float, hist_5m) -> dict:
    """
    Analyze whether an active volatile pick should be sold now.
    hist_5m: DataFrame with 5-min OHLCV for today.

    Returns:
        action:  "hold" | "watch" | "sell"
        reason:  human-readable explanation
        urgency: "low" | "medium" | "high"
        pnl_pct: current unrealized P&L from entry
    """
    if hist_5m is None or len(hist_5m) < 5:
        return {"action": "hold", "reason": "Datos insuficientes", "urgency": "low", "pnl_pct": 0.0}

    try:
        close       = hist_5m["Close"].dropna()
        volume      = hist_5m["Volume"].dropna()
        current     = float(close.iloc[-1])
        pnl_pct     = (current - entry_price) / entry_price * 100
        peak_price  = float(close.max())
        peak_gain   = (peak_price - entry_price) / entry_price * 100

        signals = []
        urgency = "low"

        # 1. Hard stop
        if pnl_pct <= -7.0:
            return {
                "action": "sell", "urgency": "high",
                "reason": f"🛑 Stop loss activado ({pnl_pct:.1f}%)",
                "pnl_pct": round(pnl_pct, 2),
            }

        # 2. Target reached
        if pnl_pct >= 10.0:
            return {
                "action": "sell", "urgency": "high",
                "reason": f"🎯 Objetivo +10% alcanzado ({pnl_pct:.1f}%)",
                "pnl_pct": round(pnl_pct, 2),
            }

        # 3. Volume fading (last 3 candles avg < 40% of peak candle volume)
        if len(volume) >= 6:
            peak_vol   = float(volume.max())
            recent_vol = float(volume.iloc[-3:].mean())
            if peak_vol > 0 and recent_vol < peak_vol * 0.35:
                signals.append("volumen desvaneciéndose")
                urgency = "medium"

        # 4. Price giving back gains (retraced >50% of intraday gain)
        if peak_gain > 4.0 and pnl_pct < peak_gain * 0.5:
            signals.append(f"precio retrocedió {peak_gain - pnl_pct:.1f}% desde el pico")
            urgency = "medium"

        # 5. RSI(3) overbought on 5-min
        rsi_val = _rsi(close, period=3)
        if rsi_val > 82:
            signals.append(f"RSI corto sobrecomprado ({rsi_val:.0f})")
            urgency = "medium"

        # 6. Extended move with modest gain — time to trim
        if len(hist_5m) > 24 and 3.0 <= pnl_pct < 8.0 and urgency == "medium":
            signals.append("movimiento extendido con ganancia moderada")

        if len(signals) >= 2:
            action = "sell"
            urgency = "high"
            reason  = "⚠️ Múltiples señales de salida: " + " · ".join(signals)
        elif len(signals) == 1:
            action  = "watch"
            reason  = f"👁 Vigilar: {signals[0]}"
        else:
            action  = "hold"
            reason  = f"✅ Mantener — momentum activo (RSI {rsi_val:.0f})"

        return {
            "action":   action,
            "reason":   reason,
            "urgency":  urgency,
            "pnl_pct":  round(pnl_pct, 2),
            "rsi":      round(rsi_val, 1),
            "peak_gain": round(peak_gain, 2),
        }

    except Exception as e:
        return {"action": "hold", "reason": f"Error: {e}", "urgency": "low", "pnl_pct": 0.0}


# ── Core scanner ───────────────────────────────────────────────────────────────

def scan_intraday_movers(force: bool = False, top_n: int = TOP_N) -> dict:
    """
    Scan for stocks moving RIGHT NOW with unusual intraday volume.

    Returns:
        alerts:        list of active alert dicts sorted by urgency score
        sell_signals:  list of {ticker, signal} for active volatile picks
        cached_at:     ISO timestamp
        market_open:   bool
    """
    from volatile_watchlist import VOLATILE_TICKERS, VOLATILE_SECTOR
    import yfinance as yf
    import pandas as pd

    # ── Cache check ────────────────────────────────────────────────────────────
    cache_path = tmp_path("intraday", "scanner_cache")
    if not force and cache_path.exists():
        cached = load_json(cache_path)
        cached_at = cached.get("cached_at", "")
        if cached_at:
            age = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds()
            if age < CACHE_TTL_MIN * 60:
                return cached

    now = datetime.now()
    # Quick market hours check (ET, approximate)
    # NYSE: 9:30–16:00 ET (UTC-5 or UTC-4 depending on DST)
    # We don't adjust for DST precisely — just use a rough window
    hour_utc = now.hour
    market_open = 14 <= hour_utc <= 21 and now.weekday() < 5  # 9:30–16:00 ET ≈ 14:30–21:00 UTC

    # ── Download 5-min candles for today ──────────────────────────────────────
    try:
        raw_5m = yf.download(
            tickers=VOLATILE_TICKERS,
            period="2d",        # 2 days to get yesterday's close for baseline
            interval="5m",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return {
            "alerts": [], "sell_signals": [], "market_open": market_open,
            "cached_at": now.isoformat(), "error": str(e),
        }

    # ── Also get prev-day close via daily data (for accurate % move) ──────────
    try:
        raw_1d = yf.download(
            tickers=VOLATILE_TICKERS,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception:
        raw_1d = None

    def _extract(raw, ticker, level=1):
        """Safely extract per-ticker slice from a multi-ticker download."""
        import numpy as np
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                lvl0 = raw.columns.get_level_values(0)
                lvl1 = raw.columns.get_level_values(1)
                if ticker in lvl1:
                    df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                elif ticker in lvl0:
                    df = raw.xs(ticker, axis=1, level=0).dropna(how="all")
                else:
                    return None
            else:
                df = raw.copy()
            # Flatten if still MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            return df if len(df) >= 3 else None
        except Exception:
            return None

    # ── Fetch breaking news ────────────────────────────────────────────────────
    news_map: dict[str, dict] = {}  # ticker → {headline, sentiment}
    try:
        news_items = _extract_news_tickers()
        for item in news_items:
            tk = item["ticker"]
            if tk not in news_map or abs(item["sentiment"]) > abs(news_map[tk]["sentiment"]):
                news_map[tk] = item
    except Exception:
        pass

    # ── Process each ticker ────────────────────────────────────────────────────
    alerts = []

    # Union of watchlist + news-extracted tickers
    all_tickers = list(VOLATILE_TICKERS)
    for tk in news_map:
        if tk not in set(all_tickers):
            all_tickers.append(tk)

    for ticker in all_tickers:
        try:
            hist_5m = _extract(raw_5m, ticker)
            if hist_5m is None or len(hist_5m) < 6:
                continue

            close_5m  = hist_5m["Close"].dropna()
            volume_5m = hist_5m["Volume"].dropna()

            if len(close_5m) < 6 or len(volume_5m) < 6:
                continue

            current_price = float(close_5m.iloc[-1])

            # Prev close from daily data (more reliable baseline)
            prev_close = None
            if raw_1d is not None:
                hist_1d = _extract(raw_1d, ticker)
                if hist_1d is not None and len(hist_1d) >= 2:
                    prev_close = float(hist_1d["Close"].dropna().iloc[-2])

            if prev_close is None:
                # Fall back to first 5-min candle of today
                prev_close = float(close_5m.iloc[0])

            if prev_close <= 0:
                continue

            price_move_pct = (current_price - prev_close) / prev_close * 100

            # Gate 1: must have moved meaningfully from prev close
            if abs(price_move_pct) < MIN_PRICE_MOVE:
                continue

            # Intraday volume spike — compare recent candles to avg candle for today
            avg_vol_5m  = float(volume_5m.mean())
            recent_vol  = float(volume_5m.iloc[-3:].mean())
            vol_spike   = recent_vol / avg_vol_5m if avg_vol_5m > 0 else 0

            # Gate 2: recent candles must show elevated volume
            if vol_spike < MIN_VOL_SPIKE:
                continue

            # Find when the volume spike started (first candle > 2x avg today)
            spike_idx = -1
            for i in range(len(volume_5m) - 1, max(0, len(volume_5m) - 30), -1):
                if float(volume_5m.iloc[i]) >= avg_vol_5m * 2.0:
                    spike_idx = i
                # Walk backwards until volume normalizes
                if i < len(volume_5m) - 1 and float(volume_5m.iloc[i]) < avg_vol_5m * 1.3:
                    break
            # spike_idx = earliest recent high-volume candle
            first_spike = max(0, spike_idx)
            phase, elapsed_min = _detect_phase(hist_5m, first_spike)

            # Skip extended moves (> 2h in) unless very strong signal
            if phase == "extended" and vol_spike < 8.0:
                continue

            # News/catalyst
            news   = news_map.get(ticker, {})
            has_news  = bool(news)
            sentiment = float(news.get("sentiment", 0.0))
            headline  = news.get("headline", "")
            if not headline:
                # Try cached news file
                try:
                    cached_news = load_json(tmp_path(ticker, "news"))
                    headlines   = (cached_news.get("top_positive_headlines") or
                                   cached_news.get("top_negative_headlines") or [""])
                    headline    = headlines[0] if headlines else ""
                    sentiment   = float(cached_news.get("sentiment_score", 0.0))
                    has_news    = bool(headline)
                except Exception:
                    pass

            # Alert score
            score = _alert_score(price_move_pct, vol_spike, sentiment, phase, has_news)
            if score < ALERT_THRESHOLD:
                continue

            # Entry / stop / target
            direction  = "long" if price_move_pct > 0 else "short"
            entry_low  = round(current_price * 0.995, 2)
            entry_high = round(current_price * 1.005, 2)
            if direction == "long":
                stop_price   = round(current_price * 0.93, 2)
                target_price = round(current_price * 1.10, 2)
            else:
                stop_price   = round(current_price * 1.07, 2)
                target_price = round(current_price * 0.90, 2)

            # RSI on 5-min
            rsi_now = _rsi(close_5m)

            # Intraday high/low for context
            high_today = float(hist_5m["High"].dropna().max()) if "High" in hist_5m.columns else current_price
            low_today  = float(hist_5m["Low"].dropna().min())  if "Low"  in hist_5m.columns else current_price

            alerts.append({
                "ticker":        ticker,
                "sector":        VOLATILE_SECTOR.get(ticker, "Externo" if ticker not in VOLATILE_SECTOR else "Unknown"),
                "price":         round(current_price, 2),
                "prev_close":    round(prev_close, 2),
                "change_pct":    round(price_move_pct, 2),
                "vol_spike":     round(vol_spike, 1),
                "direction":     direction,
                "phase":         phase,
                "elapsed_min":   elapsed_min,
                "rsi_5m":        round(rsi_now, 1),
                "alert_score":   score,
                "entry_low":     entry_low,
                "entry_high":    entry_high,
                "stop_price":    stop_price,
                "target_price":  target_price,
                "risk_reward":   round(abs(target_price - current_price) / abs(current_price - stop_price), 2),
                "headline":      headline[:120],
                "sentiment":     round(sentiment, 3),
                "has_news":      has_news,
                "high_today":    round(high_today, 2),
                "low_today":     round(low_today, 2),
            })

        except Exception:
            continue

    # Sort by score desc
    alerts.sort(key=lambda x: -x["alert_score"])

    # ── Sell signals for active volatile picks ─────────────────────────────────
    sell_signals = []
    try:
        from volatile_daily_picks import load_volatile_picks
        vpicks = load_volatile_picks()
        for pick in vpicks.get("active_picks", []):
            tk     = pick["ticker"]
            entry  = pick.get("entry_price", 0)
            hist   = _extract(raw_5m, tk)
            if entry and hist is not None:
                sig = get_sell_signals(tk, entry, hist)
                sig["ticker"] = tk
                sig["entry_price"] = entry
                sig["sector"] = pick.get("sector", "")
                sell_signals.append(sig)
    except Exception:
        pass

    # Sort sell signals — urgent ones first
    urgency_order = {"high": 0, "medium": 1, "low": 2}
    sell_signals.sort(key=lambda x: (urgency_order.get(x.get("urgency","low"), 2),
                                      -(x.get("pnl_pct", 0))))

    output = {
        "cached_at":    now.isoformat(),
        "market_open":  market_open,
        "alerts":       alerts[:top_n],
        "all_alerts":   alerts,
        "sell_signals": sell_signals,
        "total_scanned": len(all_tickers),
    }
    save_json(cache_path, output)

    n_sell = sum(1 for s in sell_signals if s.get("action") == "sell")
    print(f"[OK] Intraday scan: {len(alerts)} alerts | {n_sell} sell signals | "
          f"scanned {len(all_tickers)} tickers")
    return output


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--top",   type=int, default=8)
    args = parser.parse_args()

    data = scan_intraday_movers(force=args.force, top_n=args.top)
    print(f"\nMarket open: {data.get('market_open')}")
    print(f"Alerts: {len(data.get('alerts', []))}")

    for a in data.get("alerts", []):
        phase_icon = {"early": "🌅", "active": "📈", "extended": "⚠️"}.get(a["phase"], "❓")
        print(f"\n{phase_icon} {a['ticker']:6s} {a['change_pct']:+.1f}% "
              f"vol={a['vol_spike']:.1f}x score={a['alert_score']:.2f} "
              f"[{a['phase']} +{a['elapsed_min']}min]")
        print(f"   Entrada: ${a['entry_low']}–${a['entry_high']} | "
              f"Stop: ${a['stop_price']} | Obj: ${a['target_price']} | "
              f"R/R: {a['risk_reward']:.1f}x")
        if a["headline"]:
            print(f"   📰 {a['headline'][:80]}")

    print(f"\n── Señales de salida ──")
    for s in data.get("sell_signals", []):
        print(f"  {s['ticker']:6s} {s['action'].upper():5s} {s['pnl_pct']:+.1f}% — {s['reason']}")

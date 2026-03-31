"""
daily_picks.py — Daily top 10 watchlist + top 5 high-conviction stocks.

Flow:
  1. Takes scanner results (quick scores on 75 tickers)
  2. Filters by score, confidence, manipulation flags
  3. Builds:
       - daily_top_10  : 10 stocks being actively monitored
       - top_5_conviction : picks where algo is very confident (stricter criteria)
  4. Tracks entry price + P&L throughout the day
  5. When a pick crosses WIN/LOSS threshold → auto-learns (adjusts signal weights)
  6. Persists everything in data/daily_picks.json

Usage:
    python tools/daily_picks.py            # show today's picks
    python tools/daily_picks.py --refresh  # force rebuild from fresh scanner
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_json, save_json, load_weights, weights_path, get_float

_ROOT = Path(__file__).parent.parent
PICKS_FILE = _ROOT / "data" / "daily_picks.json"

WIN_THRESHOLD  =  5.0   # % gain to classify a pick as a win
LOSS_THRESHOLD = -3.0   # % loss to classify a pick as a stop hit
LEARNING_RATE  =  0.08  # weight nudge per win/loss event


# ── Persistence ────────────────────────────────────────────────────────────────

def _load() -> dict:
    PICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not PICKS_FILE.exists():
        return {}
    try:
        return json.loads(PICKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict):
    PICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PICKS_FILE.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


# ── Conviction criteria ────────────────────────────────────────────────────────

def _is_high_conviction(r: dict) -> bool:
    """
    Stricter filter for the Top 5 Conviction picks.
    The algo must be very confident before putting something here.
    """
    return (
        abs(r["score"]) >= 0.40                                          # strong signal
        and r.get("confidence_pct", 0) >= 62                             # high confidence
        and r.get("volume_ratio", 0) >= 0.8                              # some volume confirmation
        and len(r.get("signals", {})) >= 2                               # multiple signals agree
        and not any(                                                       # no manipulation alerts
            f["severity"] == "high"
            for f in r.get("manipulation_flags", [])
        )
        and r.get("current_price", 0) > 5                                # avoid penny stocks
    )


def _is_watchlist_candidate(r: dict) -> bool:
    """Filter for the daily top 10."""
    return (
        abs(r["score"]) >= 0.22
        and not any(
            f["severity"] == "high"
            for f in r.get("manipulation_flags", [])
        )
        and r.get("current_price", 0) > 5
    )


# ── Build a pick entry from scanner result ─────────────────────────────────────

def _build_pick(r: dict, now_str: str) -> dict:
    return {
        "ticker":            r["ticker"],
        "sector":            r.get("sector", ""),
        "recommendation":    r["recommendation"],
        "score":             r["score"],
        "confidence_pct":    r.get("confidence_pct", 0),
        "entry_price":       r["current_price"],
        "entry_time":        now_str,
        "current_price":     r["current_price"],
        "current_score":     r["score"],
        "pnl_pct":           0.0,
        "status":            "active",   # active | target_hit | stop_hit | closed
        "rsi":               r.get("rsi"),
        "volume_ratio":      r.get("volume_ratio"),
        "change_1d_pct":     r.get("change_1d_pct"),
        "change_5d_pct":     r.get("change_5d_pct"),
        "signals":           list(r.get("signals", {}).keys()),
        "manipulation_flags": r.get("manipulation_flags", []),
        "added_at":          now_str,
        "last_updated":      now_str,
        "outcome":           None,   # "win" | "loss" | "neutral" (filled on close)
    }


# ── Auto-learning: nudge weights based on pick outcome ─────────────────────────

def _learn_from_pick(pick: dict):
    """
    When a pick is auto-closed, nudge signal weights based on the outcome.
    Win  → signals that fired get a small weight boost
    Loss → signals that fired get a small weight penalty
    """
    outcome = pick.get("outcome")
    signals = pick.get("signals", [])
    if not outcome or not signals:
        return

    # Map quick-score signals to weight keys
    SIGNAL_MAP = {
        "rsi_oversold":         "rsi_oversold",
        "rsi_overbought":       "rsi_overbought",
        "golden_cross":         "ma_golden_cross",
        "death_cross":          "ma_death_cross",
        "above_both_mas":       "ma_golden_cross",
        "below_both_mas":       "ma_death_cross",
        "strong_momentum_up":   "macd_bullish",
        "strong_momentum_down": "macd_bearish",
        "volume_confirms_up":   "macd_bullish",
        "volume_confirms_down": "macd_bearish",
    }

    try:
        path = weights_path()
        weights = load_weights()
        changed = False

        for sig in signals:
            weight_key = SIGNAL_MAP.get(sig)
            if not weight_key:
                continue
            current_w = weights.get(weight_key, 1.0)
            if outcome == "win":
                new_w = min(2.0, current_w + LEARNING_RATE)
            elif outcome == "loss":
                new_w = max(0.2, current_w - LEARNING_RATE)
            else:
                continue
            weights[weight_key] = round(new_w, 4)
            changed = True

        if changed:
            weights["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_json(path, weights)
            print(f"[Learn] {pick['ticker']} {outcome} → updated weights for {signals}")

    except Exception as e:
        print(f"[Learn] Warning: could not update weights: {e}")


# ── Update existing picks with new prices ──────────────────────────────────────

def _update_pick_prices(picks: list, price_map: dict, now_str: str) -> tuple:
    """
    Refresh current_price and P&L for each active pick.
    Returns (updated_picks, newly_closed_picks).
    """
    updated     = []
    newly_closed = []

    for pick in picks:
        if pick["status"] != "active":
            updated.append(pick)
            continue

        ticker  = pick["ticker"]
        new_price = price_map.get(ticker)

        if not new_price:
            updated.append(pick)
            continue

        entry = pick["entry_price"]
        pnl   = ((new_price - entry) / entry) * 100 if entry else 0.0

        pick["current_price"] = round(new_price, 2)
        pick["pnl_pct"]       = round(pnl, 2)
        pick["last_updated"]  = now_str

        # Update current score from latest scan
        pick["current_score"] = price_map.get(f"{ticker}__score", pick["current_score"])

        # Auto-close on threshold crossing
        if pnl >= WIN_THRESHOLD:
            pick["status"]  = "target_hit"
            pick["outcome"] = "win"
            newly_closed.append(pick)
            _learn_from_pick(pick)
            print(f"[Picks] {ticker} TARGET HIT +{pnl:.1f}% — learning from win")
        elif pnl <= LOSS_THRESHOLD:
            pick["status"]  = "stop_hit"
            pick["outcome"] = "loss"
            newly_closed.append(pick)
            _learn_from_pick(pick)
            print(f"[Picks] {ticker} STOP HIT {pnl:.1f}% — learning from loss")

        updated.append(pick)

    return updated, newly_closed


# ── Main function: generate or update today's picks ────────────────────────────

def generate_daily_picks(scan_data: dict) -> dict:
    """
    Build (or refresh) the daily top 10 + top 5 conviction picks.

    - First call of the day: creates fresh picks with entry prices.
    - Subsequent calls: updates prices, P&L, and re-ranks if needed.
    - Auto-learns when picks hit WIN/LOSS threshold.
    """
    existing = _load()
    today    = datetime.now().strftime("%Y-%m-%d")
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")

    all_results = scan_data.get("all_results", [])
    if not all_results:
        return existing or {}

    # Build price map and score map from latest scan
    price_map = {}
    for r in all_results:
        t = r["ticker"]
        price_map[t]              = r.get("current_price", 0)
        price_map[f"{t}__score"]  = r.get("score", 0)

    # ── If picks exist for today → update prices only ──────────────────────────
    if existing.get("date") == today:
        # Update daily_top_10
        top10_updated, closed_10 = _update_pick_prices(
            existing.get("daily_top_10", []), price_map, now_str
        )
        # Update conviction picks
        conv_updated, closed_conv = _update_pick_prices(
            existing.get("top_5_conviction", []), price_map, now_str
        )

        # Move newly closed picks to closed list
        newly_closed = closed_10 + closed_conv
        closed_list  = existing.get("closed_picks", []) + newly_closed

        # Remove closed picks from active lists (keep in closed_picks only)
        top10_active = [p for p in top10_updated  if p["status"] == "active"]
        conv_active  = [p for p in conv_updated   if p["status"] == "active"]

        # If active top10 dropped below 7, try to fill from scan
        if len(top10_active) < 7:
            # Exclude both active AND already-closed tickers to prevent duplicates
            used_tickers = {p["ticker"] for p in top10_updated}
            candidates = [
                r for r in all_results
                if r["ticker"] not in used_tickers
                and _is_watchlist_candidate(r)
            ]
            candidates.sort(key=lambda x: abs(x["score"]), reverse=True)
            for r in candidates[:10 - len(top10_active)]:
                top10_active.append(_build_pick(r, now_str))

        # Re-sort active picks by current score
        top10_active.sort(key=lambda x: abs(x.get("current_score", x["score"])), reverse=True)
        top10_final  = (top10_active + [p for p in top10_updated if p["status"] != "active"])[:10]

        # Re-fill conviction if any closed
        if len(conv_active) < 5:
            # Exclude both active AND already-closed conviction tickers
            used_conv_tickers = {p["ticker"] for p in conv_updated}
            candidates = [
                r for r in all_results
                if r["ticker"] not in used_conv_tickers
                and _is_high_conviction(r)
            ]
            candidates.sort(key=lambda x: abs(x["score"]), reverse=True)
            for r in candidates[:5 - len(conv_active)]:
                conv_active.append(_build_pick(r, now_str))

        conv_active.sort(key=lambda x: abs(x.get("current_score", x["score"])), reverse=True)

        # Stats
        wins   = sum(1 for p in closed_list if p.get("outcome") == "win")
        losses = sum(1 for p in closed_list if p.get("outcome") == "loss")

        data = {
            **existing,
            "last_updated":       now_str,
            "daily_top_10":       top10_final[:10],
            "top_5_conviction":   conv_active[:5],
            "closed_picks":       closed_list,
            "wins_today":         wins,
            "losses_today":       losses,
        }
        _save(data)
        return data

    # ── New day → generate fresh picks ────────────────────────────────────────
    candidates = [r for r in all_results if _is_watchlist_candidate(r)]
    candidates.sort(key=lambda x: abs(x["score"]), reverse=True)

    # Mix buys and sells: up to 7 buys + 3 sells
    buys  = [r for r in candidates if r["recommendation"] == "Buy"]
    sells = [r for r in candidates if r["recommendation"] == "Sell"]

    top10_raw = []
    bi = si = 0
    while len(top10_raw) < 10 and (bi < len(buys) or si < len(sells)):
        slots_left = 10 - len(top10_raw)
        buy_slots  = min(7 - sum(1 for p in top10_raw if p["recommendation"] == "Buy"), slots_left)
        sell_slots = slots_left - max(0, buy_slots)
        if bi < len(buys) and buy_slots > 0:
            top10_raw.append(buys[bi]); bi += 1
        elif si < len(sells) and sell_slots > 0:
            top10_raw.append(sells[si]); si += 1
        else:
            break

    conviction_raw = [r for r in candidates if _is_high_conviction(r)]
    conviction_raw.sort(key=lambda x: abs(x["score"]), reverse=True)

    data = {
        "date":               today,
        "generated_at":       now_str,
        "last_updated":       now_str,
        "top_5_conviction":   [_build_pick(r, now_str) for r in conviction_raw[:5]],
        "daily_top_10":       [_build_pick(r, now_str) for r in top10_raw],
        "closed_picks":       [],
        "wins_today":         0,
        "losses_today":       0,
    }
    _save(data)
    return data


def load_daily_picks() -> dict:
    """Load today's picks from disk (no regeneration)."""
    return _load()


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from market_scanner import scan_market

    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Force fresh scanner + rebuild")
    args = parser.parse_args()

    print("Loading scanner data...")
    scan_data = scan_market(force=args.refresh)

    print("Building daily picks...")
    picks = generate_daily_picks(scan_data)

    today = picks.get("date", "?")
    print(f"\nDate: {today}  |  Updated: {picks.get('last_updated','?')}")
    print(f"Closed today: {picks.get('wins_today',0)} wins / {picks.get('losses_today',0)} losses")

    print("\n=== TOP 5 CONVICTION ===")
    for p in picks.get("top_5_conviction", []):
        print(f"  {p['ticker']:6s}  {p['recommendation']:4s}  score={p['score']:+.3f}"
              f"  conf={p['confidence_pct']}%  P&L={p['pnl_pct']:+.1f}%  [{p['status']}]")

    print("\n=== DAILY TOP 10 ===")
    for p in picks.get("daily_top_10", []):
        print(f"  {p['ticker']:6s}  {p['recommendation']:4s}  score={p['score']:+.3f}"
              f"  P&L={p['pnl_pct']:+.1f}%  [{p['status']}]")

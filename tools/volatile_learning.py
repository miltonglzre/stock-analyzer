"""
volatile_learning.py — Learn from closed volatile paper trades.

Analyzes which catalyst patterns (volume spike, price momentum, news type,
sector) actually predicted successful moves, then updates the weights used
by volatile_scanner.py to score future opportunities.

Weights stored in: data/volatile_weights.json

Usage:
    python tools/volatile_learning.py
    python tools/volatile_learning.py --min-samples 3
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path, load_json, save_json, _ROOT


# ── Paths ──────────────────────────────────────────────────────────────────────

def volatile_weights_path() -> Path:
    p = _ROOT / "data" / "volatile_weights.json"
    p.parent.mkdir(exist_ok=True)
    return p


DEFAULT_VOLATILE_WEIGHTS = {
    # Catalyst score component weights (must sum to 1.0)
    "w_volume":    0.35,
    "w_price":     0.35,
    "w_news":      0.30,

    # Catalyst type multipliers (applied to news component when event detected)
    "mult_fda":              1.8,
    "mult_earnings_beat":    1.6,
    "mult_earnings_miss":    1.4,
    "mult_acquisition":      1.7,
    "mult_guidance_raise":   1.3,
    "mult_guidance_cut":     1.3,
    "mult_analyst_upgrade":  1.2,
    "mult_analyst_downgrade":1.2,

    # Sector bias adjustments (multiplier on final score for this sector)
    "sector_Biotech":      1.0,
    "sector_EV":           1.0,
    "sector_Crypto":       1.0,
    "sector_Aerospace":    1.0,
    "sector_Fintech":      1.0,
    "sector_Tech":         1.0,
    "sector_Quantum":      1.0,
    "sector_Unknown":      1.0,

    # Squeeze bonus threshold
    "squeeze_bonus":       0.15,
    "squeeze_vol_min":     5.0,   # min volume ratio to qualify for squeeze bonus
    "squeeze_rsi_max":     35.0,  # max RSI 2d ago to qualify

    "last_updated": None,
    "total_closed":  0,
}


def load_volatile_weights() -> dict:
    saved = load_json(volatile_weights_path())
    weights = dict(DEFAULT_VOLATILE_WEIGHTS)
    for k, v in saved.items():
        if k in weights:
            weights[k] = v
    return weights


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze_volatile_outcomes(min_samples: int = 3) -> dict:
    """
    Query closed volatile paper trades and compute:
    - Win rate by catalyst event type
    - Win rate by sector
    - Average volume_ratio / price_change for wins vs losses

    Returns a dict of insights used to update weights.
    """
    db = db_path()
    if not db.exists():
        print("[INFO] Database not found.")
        return {}

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("""
            SELECT ticker, outcome, notes
            FROM trades
            WHERE is_paper=1 AND trade_type='volatile'
              AND outcome IS NOT NULL
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        print("[INFO] No closed volatile trades yet.")
        return {}

    total = len(rows)
    wins  = sum(1 for r in rows if r[1] == "win")
    print(f"\n=== Volatile Trade Summary ===")
    print(f"  Total closed: {total}  |  Wins: {wins}  |  Win rate: {wins/total*100:.1f}%")

    # Parse events and volume/price from notes field
    # notes format: "target=X stop=Y events=[...] vol_ratio=X price_chg=X sector=X"
    import re

    def _parse(notes: str, key: str, default=None):
        if not notes:
            return default
        m = re.search(rf"{key}=([^\s]+)", notes or "")
        if not m:
            return default
        return m.group(1)

    # Event type win rates
    event_stats: dict[str, dict] = {}
    sector_stats: dict[str, dict] = {}

    for ticker, outcome, notes in rows:
        is_win = outcome == "win"

        # Events (stored as comma-separated in notes if available)
        events_str = _parse(notes, "events", "")
        events = [e.strip() for e in events_str.split(",") if e.strip()] if events_str else []

        for ev in events:
            if ev not in event_stats:
                event_stats[ev] = {"wins": 0, "total": 0}
            event_stats[ev]["total"] += 1
            if is_win:
                event_stats[ev]["wins"] += 1

        # Sector
        sector = _parse(notes, "sector", "Unknown") or "Unknown"
        if sector not in sector_stats:
            sector_stats[sector] = {"wins": 0, "total": 0}
        sector_stats[sector]["total"] += 1
        if is_win:
            sector_stats[sector]["wins"] += 1

    if event_stats:
        print("\n  Event type win rates:")
        for ev, s in sorted(event_stats.items(), key=lambda x: -x[1]["wins"]/max(x[1]["total"],1)):
            if s["total"] >= min_samples:
                wr = s["wins"] / s["total"] * 100
                print(f"    {ev:<30} {wr:.1f}%  ({s['total']} trades)")

    if sector_stats:
        print("\n  Sector win rates:")
        for sec, s in sorted(sector_stats.items(), key=lambda x: -x[1]["wins"]/max(x[1]["total"],1)):
            if s["total"] >= min_samples:
                wr = s["wins"] / s["total"] * 100
                print(f"    {sec:<20} {wr:.1f}%  ({s['total']} trades)")

    return {
        "total": total,
        "wins":  wins,
        "event_stats":  event_stats,
        "sector_stats": sector_stats,
        "min_samples":  min_samples,
    }


def update_volatile_weights(insights: dict, lr: float = 0.2) -> dict:
    """
    Update volatile_weights.json using EMA update rule:
        new_weight = old * (1-lr) + target * lr

    Catalyst multipliers: higher win rate → higher multiplier (1.0 – 2.0)
    Sector bias:          higher win rate → higher multiplier (0.8 – 1.3)
    """
    if not insights or insights.get("total", 0) == 0:
        print("[INFO] No data to update volatile weights.")
        return load_volatile_weights()

    weights = load_volatile_weights()
    event_stats  = insights.get("event_stats", {})
    sector_stats = insights.get("sector_stats", {})
    min_samples  = insights.get("min_samples", 3)
    updates = []

    # ── Event multipliers ──────────────────────────────────────────────────────
    event_key_map = {
        "fda":              "mult_fda",
        "earnings_beat":    "mult_earnings_beat",
        "earnings_miss":    "mult_earnings_miss",
        "acquisition":      "mult_acquisition",
        "guidance_raise":   "mult_guidance_raise",
        "guidance_cut":     "mult_guidance_cut",
        "analyst_upgrade":  "mult_analyst_upgrade",
        "analyst_downgrade":"mult_analyst_downgrade",
    }
    for ev, wk in event_key_map.items():
        if ev not in event_stats:
            continue
        s = event_stats[ev]
        if s["total"] < min_samples:
            continue
        acc = s["wins"] / s["total"]
        # Map accuracy 0-1 → multiplier 1.0-2.0
        target = 1.0 + acc
        old = weights.get(wk, 1.0)
        new = round(max(1.0, min(2.0, old * (1 - lr) + target * lr)), 4)
        weights[wk] = new
        updates.append((wk, old, new, acc * 100, s["total"]))

    # ── Sector bias ────────────────────────────────────────────────────────────
    for sector, s in sector_stats.items():
        if s["total"] < min_samples:
            continue
        wk = f"sector_{sector}"
        if wk not in DEFAULT_VOLATILE_WEIGHTS:
            weights[wk] = 1.0  # new sector discovered
        acc = s["wins"] / s["total"]
        # Map accuracy 0-1 → bias 0.8-1.3
        target = 0.8 + acc * 0.5
        old = weights.get(wk, 1.0)
        new = round(max(0.8, min(1.3, old * (1 - lr) + target * lr)), 4)
        weights[wk] = new
        updates.append((wk, old, new, acc * 100, s["total"]))

    weights["last_updated"] = datetime.now().isoformat()
    weights["total_closed"] = insights["total"]
    save_json(volatile_weights_path(), weights)

    if updates:
        print("\n=== Volatile Weight Updates ===")
        print(f"  {'Key':<30} {'Old':>7} {'New':>7} {'WinRate':>9} {'N':>5}")
        print("  " + "-" * 60)
        for wk, old, new, wr, n in sorted(updates, key=lambda x: -x[3]):
            arrow = "↑" if new > old else "↓" if new < old else "="
            print(f"  {wk:<30} {old:>7.3f} {new:>7.3f} {wr:>8.1f}% {n:>5} {arrow}")
        print(f"\n  Weights saved → data/volatile_weights.json")
    else:
        print("[INFO] No volatile weights updated (insufficient samples).")

    return weights


def run_volatile_learning_cycle(min_samples: int = 3) -> dict:
    """Full volatile learning cycle: analyze → update weights."""
    print(f"\n{'='*55}")
    print(f"  VOLATILE LEARNING CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    insights = analyze_volatile_outcomes(min_samples)
    if not insights:
        return {"status": "skipped", "reason": "no closed volatile trades"}

    new_weights = update_volatile_weights(insights)
    return {
        "status":         "ok",
        "total_closed":   insights["total"],
        "weights_updated": new_weights,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run volatile learning cycle")
    parser.add_argument("--min-samples", type=int, default=3)
    args = parser.parse_args()
    run_volatile_learning_cycle(args.min_samples)

"""
volatile_daily_picks.py — Daily volatile picks tracker (independent from daily_picks.py).

Criteria: catalyst-based (volatile_scanner), 3-day max hold, +10%/-7% win/loss gates.
Stores 8 active picks at a time in data/volatile_daily_picks.json.

This is a completely separate learning track from the 10-day fundamental picks:
  - Source:  volatile_scanner  (catalyst score: volume spike + price move + news)
  - Window:  3 trading days
  - Win:     +10% gain
  - Loss:    -7% loss (tighter because volatile stocks whip hard)
  - Limit:   8 active picks
  - Learn:   adjusts volatile_weights.json on each close

Usage:
    python tools/volatile_daily_picks.py             # show current picks
    python tools/volatile_daily_picks.py --refresh   # force rebuild
"""

import sys
import json
from pathlib import Path
from datetime import datetime, date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_json, save_json

_ROOT       = Path(__file__).parent.parent
PICKS_FILE  = _ROOT / "data" / "volatile_daily_picks.json"

WIN_THRESHOLD   =  10.0   # +10% to classify as win
LOSS_THRESHOLD  =  -7.0   # -7%  to classify as stop hit
MAX_ACTIVE      =   8     # max simultaneous volatile picks
HOLD_DAYS       =   3     # auto-close after 3 days regardless


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


# ── Build a pick entry from scanner opportunity ────────────────────────────────

def _build_pick(opp: dict, now_str: str) -> dict:
    events = opp.get("events", [])
    return {
        "ticker":         opp["ticker"],
        "sector":         opp.get("sector", "Unknown"),
        "direction":      opp.get("direction", "up"),
        "entry_price":    opp["price"],
        "current_price":  opp["price"],
        "pnl_pct":        0.0,
        "catalyst_score": opp.get("catalyst_score", 0.0),
        "volume_ratio":   opp.get("volume_ratio", 0.0),
        "sentiment":      opp.get("sentiment_score", 0.0),
        "events":         events,
        "primary_event":  events[0] if events else "volume_spike",
        "headline":       opp.get("headline", "")[:120],
        "status":         "active",   # active | win | loss | expired
        "outcome":        None,
        "added_at":       now_str,
        "expires_at":     (date.today() + timedelta(days=HOLD_DAYS)).isoformat(),
        "last_updated":   now_str,
    }


# ── Auto-learning when a pick closes ─────────────────────────────────────────

def _learn_from_pick(pick: dict):
    """Trigger volatile_learning on each closed pick."""
    try:
        from volatile_learning import run_volatile_learning_cycle
        run_volatile_learning_cycle(min_samples=1)
    except Exception as e:
        print(f"[VPicks] Learning update failed: {e}")


# ── Update prices and auto-close ──────────────────────────────────────────────

def _update_prices(picks: list, price_map: dict, now_str: str) -> tuple[list, list]:
    """Refresh prices, close on threshold or expiry. Returns (updated, newly_closed)."""
    updated      = []
    newly_closed = []
    today        = date.today()

    for pick in picks:
        if pick["status"] != "active":
            updated.append(pick)
            continue

        ticker    = pick["ticker"]
        new_price = price_map.get(ticker)
        if not new_price:
            updated.append(pick)
            continue

        entry = pick["entry_price"]
        # For "down" direction picks, P&L is inverted (short-side)
        if pick.get("direction") == "down":
            pnl = ((entry - new_price) / entry) * 100
        else:
            pnl = ((new_price - entry) / entry) * 100

        pick["current_price"] = round(new_price, 2)
        pick["pnl_pct"]       = round(pnl, 2)
        pick["last_updated"]  = now_str

        expires = pick.get("expires_at", "")
        expired = expires and date.fromisoformat(expires) <= today

        if pnl >= WIN_THRESHOLD:
            pick["status"]  = "win"
            pick["outcome"] = "win"
            newly_closed.append(pick)
            _learn_from_pick(pick)
            print(f"[VPicks] {ticker} WIN +{pnl:.1f}%")
        elif pnl <= LOSS_THRESHOLD:
            pick["status"]  = "loss"
            pick["outcome"] = "loss"
            newly_closed.append(pick)
            _learn_from_pick(pick)
            print(f"[VPicks] {ticker} STOP {pnl:.1f}%")
        elif expired:
            pick["status"]  = "expired"
            pick["outcome"] = "neutral"
            newly_closed.append(pick)
            print(f"[VPicks] {ticker} EXPIRED {pnl:+.1f}%")

        updated.append(pick)

    return updated, newly_closed


# ── Main function ──────────────────────────────────────────────────────────────

def generate_volatile_picks(scan_data: dict) -> dict:
    """
    Build or refresh volatile daily picks from scanner data.

    - Updates prices and closes picks that hit thresholds or expiry.
    - Fills empty slots with new scanner opportunities.
    - Always keeps up to MAX_ACTIVE picks running.
    """
    existing = _load()
    today    = date.today().isoformat()
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")

    opportunities = scan_data.get("opportunities", [])
    if not opportunities and not existing:
        return {}

    # Build price map from scan results
    price_map = {o["ticker"]: o["price"] for o in scan_data.get("all_results", opportunities)}

    active     = existing.get("active_picks", [])
    closed_all = existing.get("closed_picks", [])

    # Update existing active picks
    active, newly_closed = _update_prices(active, price_map, now_str)
    closed_all = closed_all + newly_closed

    # Keep only still-active after threshold/expiry checks
    still_active = [p for p in active if p["status"] == "active"]

    # Fill empty slots — exclude active AND recently-closed to prevent duplicates
    active_tickers = {p["ticker"] for p in still_active} | {p["ticker"] for p in closed_all}
    slots_available = MAX_ACTIVE - len(still_active)

    for opp in opportunities:
        if slots_available <= 0:
            break
        if opp["ticker"] in active_tickers:
            continue
        still_active.append(_build_pick(opp, now_str))
        active_tickers.add(opp["ticker"])
        slots_available -= 1

    # Stats
    wins   = sum(1 for p in closed_all if p.get("outcome") == "win")
    losses = sum(1 for p in closed_all if p.get("outcome") == "loss")
    total_closed = len(closed_all)
    win_rate = round(wins / total_closed * 100) if total_closed > 0 else 0

    data = {
        "date":          today,
        "last_updated":  now_str,
        "active_picks":  still_active[:MAX_ACTIVE],
        "closed_picks":  closed_all[-50:],   # keep last 50 for display
        "wins_total":    wins,
        "losses_total":  losses,
        "win_rate":      win_rate,
        "total_closed":  total_closed,
    }
    _save(data)
    return data


def load_volatile_picks() -> dict:
    """Load current volatile picks from disk (no regeneration)."""
    return _load()


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from volatile_scanner import scan_volatile_market

    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    scan = scan_volatile_market(force=args.refresh)
    picks = generate_volatile_picks(scan)

    active = picks.get("active_picks", [])
    closed = picks.get("closed_picks", [])
    print(f"\n{'─'*55}")
    print(f"  VOLATILE PICKS  |  {picks.get('date','')}  |  WR: {picks.get('win_rate',0)}%")
    print(f"{'─'*55}")
    for p in active:
        evts = ",".join(p.get("events", [])[:2]) or "vol_spike"
        print(f"  {p['ticker']:6s} {p['direction']:4s} "
              f"score={p['catalyst_score']:.2f} "
              f"entry=${p['entry_price']:.2f}  [{evts}]")
    print(f"\nCerrados: {len(closed)} | Wins: {picks.get('wins_total',0)} | Stops: {picks.get('losses_total',0)}")

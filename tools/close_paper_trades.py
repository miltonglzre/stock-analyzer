"""
close_paper_trades.py — Auto-close paper trades that hit target, stop, or expiry.

Fetches current price for each open paper trade and closes it when:
  - Price >= target_price  → win
  - Price <= stop_loss     → loss
  - Entry date older than eval_days → forced close at current price

Returns a list of closed trade summaries.

Usage:
    python tools/close_paper_trades.py
    python tools/close_paper_trades.py --days 7
"""

import sys
import re
import sqlite3
import argparse
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path, get_int, get_float


def _parse_note_float(notes: str, key: str) -> float | None:
    if not notes:
        return None
    m = re.search(rf"{key}=([0-9.]+)", notes)
    return float(m.group(1)) if m else None


def _fetch_price(ticker: str) -> float:
    import yfinance as yf
    fi = yf.Ticker(ticker).fast_info
    price = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
    if not price:
        raise ValueError(f"Could not fetch price for {ticker}")
    return float(price)


def close_paper_trades(eval_days: int = 10,
                       trade_type: str = "regular") -> list[dict]:
    """
    Evaluate all open auto paper trades of a given type and close resolved ones.
    trade_type: 'regular' (10d, 3% thresholds) or 'volatile' (3d, 10% thresholds).
    Returns list of dicts describing each closed trade.
    """
    if trade_type == "volatile":
        win_pct  = get_float("VOLATILE_WIN_THRESHOLD_PCT",   10.0)
        loss_pct = get_float("VOLATILE_LOSS_THRESHOLD_PCT", -7.0)
    else:
        win_pct  = get_float("WIN_THRESHOLD_PCT",   3.0)
        loss_pct = get_float("LOSS_THRESHOLD_PCT", -3.0)

    cutoff = date.today() - timedelta(days=eval_days)

    db = db_path()
    if not db.exists():
        return []

    conn = sqlite3.connect(db)
    try:
        open_trades = conn.execute(
            """SELECT id, ticker, entry_date, entry_price, recommendation, notes
               FROM trades
               WHERE exit_date IS NULL AND is_paper=1 AND trade_type=?
               ORDER BY entry_date""",
            (trade_type,)
        ).fetchall()
    finally:
        conn.close()

    if not open_trades:
        return []

    closed = []

    for trade_id, ticker, entry_date_str, entry_price, rec, notes in open_trades:
        target = _parse_note_float(notes, "target")
        stop   = _parse_note_float(notes, "stop")
        entry_dt = date.fromisoformat(entry_date_str)

        try:
            current = _fetch_price(ticker)
        except Exception as e:
            print(f"[WARN] Could not fetch {ticker}: {e}")
            continue

        pnl_pct = (current - entry_price) / entry_price * 100
        reason  = None

        if target and current >= target:
            reason = f"hit_target (${current:.2f} >= ${target:.2f})"
        elif stop and current <= stop:
            reason = f"hit_stop (${current:.2f} <= ${stop:.2f})"
        elif entry_dt <= cutoff:
            reason = f"expired ({eval_days}d window)"

        if reason is None:
            continue

        # Classify outcome
        if pnl_pct >= win_pct:
            outcome = "win"
        elif pnl_pct <= loss_pct:
            outcome = "loss"
        else:
            outcome = "neutral"

        conn = sqlite3.connect(db)
        try:
            conn.execute(
                """UPDATE trades
                   SET exit_date=?, exit_price=?, pnl_pct=?, outcome=?,
                       notes = notes || ' | closed: ' || ?
                   WHERE id=?""",
                (date.today().isoformat(), round(current, 4),
                 round(pnl_pct, 4), outcome, reason, trade_id),
            )
            conn.commit()
        finally:
            conn.close()

        closed.append({
            "trade_id":    trade_id,
            "ticker":      ticker,
            "rec":         rec,
            "entry_price": entry_price,
            "exit_price":  round(current, 4),
            "pnl_pct":     round(pnl_pct, 2),
            "outcome":     outcome,
            "reason":      reason,
        })
        print(f"[CLOSED] #{trade_id} {ticker} {outcome.upper()} {pnl_pct:+.2f}% — {reason}")

    return closed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Close expired auto paper trades")
    parser.add_argument("--days", type=int, default=10, help="Evaluation window in days")
    args = parser.parse_args()
    results = close_paper_trades(args.days)
    print(f"\n{len(results)} trade(s) closed.")

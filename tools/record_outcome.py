"""
record_outcome.py — Close an open trade and record the P&L result.

Auto-classifies outcome as win / loss / neutral based on .env thresholds.

Usage:
    python tools/record_outcome.py 7 183.20
    python tools/record_outcome.py 7 183.20 --notes "Hit target, profit taken"
"""

import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path, get_float


def record_outcome(trade_id: int, exit_price: float, notes: str = ""):
    win_threshold = get_float("WIN_THRESHOLD_PCT", 5.0)
    loss_threshold = get_float("LOSS_THRESHOLD_PCT", -5.0)

    db = db_path()
    if not db.exists():
        print(f"[ERROR] Database not found at {db}. Run: python tools/db_init.py")
        sys.exit(1)

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT id, ticker, entry_price, exit_date FROM trades WHERE id = ?",
            (trade_id,)
        ).fetchone()

        if not row:
            print(f"[ERROR] Trade #{trade_id} not found.")
            sys.exit(1)

        _, ticker, entry_price, existing_exit = row

        if existing_exit:
            print(f"[WARN] Trade #{trade_id} already closed on {existing_exit}. Overwriting...")

        if exit_price <= 0:
            print(f"[ERROR] Exit price must be positive. Got: {exit_price}")
            sys.exit(1)

        pnl_pct = round((exit_price - entry_price) / entry_price * 100, 4)

        if pnl_pct >= win_threshold:
            outcome = "win"
        elif pnl_pct <= loss_threshold:
            outcome = "loss"
        else:
            outcome = "neutral"

        existing_notes = conn.execute("SELECT notes FROM trades WHERE id=?", (trade_id,)).fetchone()[0] or ""
        combined_notes = f"{existing_notes} | Exit: {notes}".strip(" |") if notes else existing_notes

        conn.execute("""
            UPDATE trades
            SET exit_date = ?, exit_price = ?, pnl_pct = ?, outcome = ?, notes = ?
            WHERE id = ?
        """, (date.today().isoformat(), exit_price, pnl_pct, outcome, combined_notes, trade_id))
        conn.commit()

        emoji = "WIN" if outcome == "win" else "LOSS" if outcome == "loss" else "NEUTRAL"
        sign = "+" if pnl_pct >= 0 else ""
        print(f"[OK] Trade #{trade_id} ({ticker}) closed -> [{emoji}] P&L: {sign}{pnl_pct:.2f}%")
        print(f"     Entry: ${entry_price:.2f}  Exit: ${exit_price:.2f}")
        print(f"\nRun the learning cycle to update signal weights:")
        print(f"  python tools/analyze_errors.py")
        print(f"  python tools/adjust_weights.py")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Record trade exit and P&L")
    parser.add_argument("trade_id", type=int, help="Trade ID from record_trade.py")
    parser.add_argument("exit_price", type=float, help="Exit price in USD")
    parser.add_argument("--notes", default="", help="Optional notes")
    args = parser.parse_args()
    record_outcome(args.trade_id, args.exit_price, args.notes)


if __name__ == "__main__":
    main()

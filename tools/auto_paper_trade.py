"""
auto_paper_trade.py — Auto-register analysis recommendations as paper trades.

Called automatically after each analysis in app.py.
Only records Buy/Sell recommendations; skips if a paper trade is already
open for that ticker or if the open count is at the configured limit.

Usage (standalone):
    python tools/auto_paper_trade.py AAPL
"""

import sys
import sqlite3
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path, tmp_path, load_json, get_int


def auto_paper_trade(ticker: str, decision: dict) -> int | None:
    """
    Record a Buy/Sell decision as an auto paper trade.
    Returns the new trade_id, or None if skipped.
    """
    ticker = ticker.upper()
    rec = decision.get("recommendation", "")
    if rec not in ("Buy", "Sell"):
        return None

    price = decision.get("current_price") or decision.get("entry_zone_low")
    if not price or price <= 0:
        return None

    target    = decision.get("target_price")
    stop      = decision.get("stop_loss")
    verdict   = decision.get("verdict", "Neutral")
    conf      = decision.get("confidence_pct", 50)

    db = db_path()
    if not db.exists():
        return None

    conn = sqlite3.connect(db)
    try:
        # Skip if open paper trade already exists for this ticker
        existing = conn.execute(
            "SELECT id FROM trades WHERE ticker=? AND exit_date IS NULL AND is_paper=1",
            (ticker,)
        ).fetchone()
        if existing:
            return None

        # Skip if at the open-trade limit
        open_count = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE exit_date IS NULL AND is_paper=1"
        ).fetchone()[0]
        max_open = get_int("MAX_PAPER_TRADES", 25)
        if open_count >= max_open:
            return None

        notes = f"target={target} stop={stop}"
        cur = conn.execute(
            """INSERT INTO trades
               (ticker, entry_date, entry_price, recommendation,
                confidence_pct, verdict, notes, is_paper)
               VALUES (?,?,?,?,?,?,?,1)""",
            (ticker, date.today().isoformat(), price, rec, conf, verdict, notes),
        )
        trade_id = cur.lastrowid

        # Record all signals from the most recent technicals
        signals = load_json(tmp_path(ticker, "technicals")).get("signals", {})
        for sig, fired in signals.items():
            direction = (
                "bullish"
                if any(w in sig for w in ["golden", "oversold", "bullish", "strong", "bounce"])
                else "bearish"
            )
            conn.execute(
                """INSERT INTO trade_signals
                   (trade_id, signal_type, signal_value, signal_fired, signal_direction)
                   VALUES (?,?,?,?,?)""",
                (trade_id, sig, None, 1 if fired else 0, direction),
            )

        conn.commit()
        return trade_id
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/auto_paper_trade.py <TICKER>")
        sys.exit(1)
    tk = sys.argv[1].upper()
    dec = load_json(tmp_path(tk, "decision"))
    if not dec:
        print(f"[ERROR] No decision found for {tk}. Run an analysis first.")
        sys.exit(1)
    result = auto_paper_trade(tk, dec)
    print(f"[OK] Paper trade #{result} created." if result else "[INFO] Skipped (already open or limit reached).")

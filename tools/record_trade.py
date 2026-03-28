"""
record_trade.py — Log a new trade entry to the learning system database.

Reads the most recent analysis_reports row for the ticker to auto-populate signals.

Usage:
    python tools/record_trade.py AAPL 175.40 Buy
    python tools/record_trade.py TSLA 250.00 Sell --notes "Overvalued after earnings"
"""

import sys
import sqlite3
import json
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path, tmp_path, load_json


def record_trade(ticker: str, entry_price: float, recommendation: str, notes: str = "") -> int:
    ticker = ticker.upper()
    recommendation = recommendation.capitalize()

    if recommendation not in ("Buy", "Sell", "Wait"):
        print(f"[ERROR] Recommendation must be Buy, Sell, or Wait. Got: '{recommendation}'")
        sys.exit(1)

    # Load most recent decision for this ticker from .tmp/
    decision = load_json(tmp_path(ticker, "decision"))
    if not decision:
        print(f"[ERROR] No analysis found for {ticker}. Run stock_analyzer.py first.")
        sys.exit(1)

    verdict = decision.get("verdict", "Neutral")
    confidence_pct = decision.get("confidence_pct", 50)
    signals = decision.get("signals_active", {})

    db = db_path()
    if not db.exists():
        print(f"[ERROR] Database not found at {db}. Run: python tools/db_init.py")
        sys.exit(1)

    conn = sqlite3.connect(db)
    try:
        cur = conn.execute("""
            INSERT INTO trades
              (ticker, entry_date, entry_price, recommendation, confidence_pct, verdict, notes)
            VALUES (?,?,?,?,?,?,?)
        """, (ticker, date.today().isoformat(), entry_price, recommendation, confidence_pct, verdict, notes))
        trade_id = cur.lastrowid

        # Record each signal that fired
        for signal_type, fired in signals.items():
            direction = "bullish" if "golden" in signal_type or "oversold" in signal_type \
                        or "bullish" in signal_type or "strong" in signal_type \
                        or "bounce" in signal_type else "bearish"
            conn.execute("""
                INSERT INTO trade_signals
                  (trade_id, signal_type, signal_value, signal_fired, signal_direction)
                VALUES (?,?,?,?,?)
            """, (trade_id, signal_type, None, 1 if fired else 0, direction))

        # Also record all known signal types that did NOT fire
        all_signals = load_json(tmp_path(ticker, "technicals")).get("signals", {})
        for signal_type, fired in all_signals.items():
            if signal_type not in signals:
                direction = "bullish" if "golden" in signal_type or "oversold" in signal_type \
                            or "bullish" in signal_type or "strong" in signal_type else "bearish"
                conn.execute("""
                    INSERT INTO trade_signals
                      (trade_id, signal_type, signal_value, signal_fired, signal_direction)
                    VALUES (?,?,?,?,?)
                """, (trade_id, signal_type, None, 1 if fired else 0, direction))

        conn.commit()
        print(f"[OK] Trade #{trade_id} recorded: {recommendation} {ticker} @ ${entry_price:.2f}")
        print(f"     Verdict: {verdict} ({confidence_pct}% confidence)")
        print(f"     Signals recorded: {len(signals)} active")
        print(f"\n     When you close this position, run:")
        print(f"     python tools/record_outcome.py {trade_id} <exit_price>")
        return trade_id
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Record a new trade entry")
    parser.add_argument("ticker", help="Ticker symbol (e.g. AAPL)")
    parser.add_argument("entry_price", type=float, help="Entry price in USD")
    parser.add_argument("recommendation", help="Buy / Sell / Wait")
    parser.add_argument("--notes", default="", help="Optional notes about the trade")
    args = parser.parse_args()
    record_trade(args.ticker, args.entry_price, args.recommendation, args.notes)


if __name__ == "__main__":
    main()

"""
learning_cycle.py — Full auto-learning cycle: close trades → analyze → adjust weights.

Runs the complete feedback loop:
  1. Close paper trades that hit target, stop, or expiry window
  2. If enough new data, analyze signal accuracy
  3. Adjust signal weights using exponential moving average
  4. Return a summary report

Usage:
    python tools/learning_cycle.py
    python tools/learning_cycle.py --days 7 --min-trades 5
"""

import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path
from close_paper_trades import close_paper_trades
from analyze_errors import analyze_errors
from adjust_weights import adjust_weights


def run_learning_cycle(eval_days: int = 10, min_new_trades: int = 3) -> dict:
    """
    Execute the full learning loop.
    Returns a summary dict with status, trades closed, and weight changes.
    """
    print(f"\n{'='*55}")
    print(f"  CICLO DE APRENDIZAJE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    # ── Step 1: Close expired paper trades (both tracks) ──────────────────────
    print("\n[1/3] Cerrando paper trades vencidos...")
    reg_closed  = close_paper_trades(eval_days, trade_type="regular")
    vol_closed  = close_paper_trades(3,         trade_type="volatile")
    closed = reg_closed + vol_closed
    wins    = sum(1 for t in closed if t["outcome"] == "win")
    losses  = sum(1 for t in closed if t["outcome"] == "loss")
    neutral = sum(1 for t in closed if t["outcome"] == "neutral")
    print(f"      Regular: {len(reg_closed)} cerrados | Volátiles: {len(vol_closed)} cerrados")
    print(f"      Total: {len(closed)}  (W:{wins} L:{losses} N:{neutral})")

    # ── Check if enough data to learn ────────────────────────────────────────
    db = db_path()
    total_closed = 0
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            total_closed = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE is_paper=1 AND outcome IS NOT NULL"
            ).fetchone()[0]
        finally:
            conn.close()

    if len(closed) < min_new_trades and total_closed < 10:
        msg = (f"Solo {len(closed)} trades nuevos cerrados "
               f"(mínimo {min_new_trades}) y {total_closed} históricos. "
               f"Esperando más datos.")
        print(f"\n[INFO] {msg}")
        return {
            "status":        "skipped",
            "reason":        msg,
            "trades_closed": len(closed),
            "total_closed":  total_closed,
        }

    # ── Step 2: Analyze signal accuracy ───────────────────────────────────────
    print("\n[2/3] Analizando precisión de señales...")
    accuracy = analyze_errors(min_samples=3)

    # ── Step 3: Adjust weights ────────────────────────────────────────────────
    print("\n[3/3] Ajustando pesos...")
    new_weights = adjust_weights()

    print(f"\n{'='*55}")
    print(f"  Ciclo completado. {len(new_weights)} señales actualizadas.")
    print(f"{'='*55}\n")

    return {
        "status":         "ok",
        "trades_closed":  len(closed),
        "total_closed":   total_closed,
        "wins":           wins,
        "losses":         losses,
        "neutral":        neutral,
        "signals_updated": len(new_weights),
        "new_weights":    new_weights,
        "accuracy":       accuracy,
        "timestamp":      datetime.now().isoformat(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full auto-learning cycle")
    parser.add_argument("--days",       type=int, default=10,
                        help="Evaluation window in days (default 10)")
    parser.add_argument("--min-trades", type=int, default=3,
                        help="Minimum new closed trades to trigger weight update (default 3)")
    args = parser.parse_args()
    run_learning_cycle(args.days, args.min_trades)

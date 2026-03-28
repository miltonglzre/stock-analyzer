"""
analyze_errors.py — Audit signal accuracy from closed trade history.

Queries trades.db and computes per-signal win/loss accuracy rates.
Prints a table showing which signals are reliable and which should be downweighted.

Usage:
    python tools/analyze_errors.py
    python tools/analyze_errors.py --min-samples 3
"""

import sys
import sqlite3
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _console = Console()
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def analyze_errors(min_samples: int = 1) -> dict:
    db = db_path()
    if not db.exists():
        print("[ERROR] Database not found. Run: python tools/db_init.py")
        sys.exit(1)

    conn = sqlite3.connect(db)
    try:
        # Summary of all closed trades
        total_rows = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE outcome IS NOT NULL"
        ).fetchone()[0]
        wins = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE outcome='win'"
        ).fetchone()[0]
        losses = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE outcome='loss'"
        ).fetchone()[0]
        neutrals = total_rows - wins - losses

        print(f"\n=== Trade Summary ===")
        print(f"  Total closed trades: {total_rows}")
        print(f"  Wins:    {wins}  |  Losses: {losses}  |  Neutral: {neutrals}")
        if total_rows > 0:
            overall_wr = wins / total_rows * 100
            print(f"  Overall win rate: {overall_wr:.1f}%")

        if total_rows == 0:
            print("\n[INFO] No closed trades yet. Record some trades first.")
            return {}

        # Per-signal accuracy
        rows = conn.execute("""
            SELECT
                ts.signal_type,
                COUNT(*)                                                     AS total,
                SUM(CASE WHEN t.outcome = 'win' THEN 1 ELSE 0 END)          AS wins,
                SUM(CASE WHEN t.outcome = 'loss' THEN 1 ELSE 0 END)         AS losses,
                SUM(CASE WHEN ts.signal_fired = 1 AND t.outcome = 'win' THEN 1 ELSE 0 END)  AS fired_wins,
                SUM(CASE WHEN ts.signal_fired = 1 AND t.outcome = 'loss' THEN 1 ELSE 0 END) AS fired_losses,
                SUM(ts.signal_fired)                                         AS times_fired
            FROM trade_signals ts
            JOIN trades t ON ts.trade_id = t.id
            WHERE t.outcome IS NOT NULL
            GROUP BY ts.signal_type
            ORDER BY ts.signal_type
        """).fetchall()
    finally:
        conn.close()

    results = {}
    for row in rows:
        signal_type, total, wins_all, losses_all, fired_wins, fired_losses, times_fired = row
        fired_total = (fired_wins or 0) + (fired_losses or 0)
        if fired_total < min_samples:
            continue
        accuracy = fired_wins / fired_total * 100 if fired_total > 0 else 0
        results[signal_type] = {
            "accuracy_pct":  round(accuracy, 1),
            "fired_wins":    fired_wins or 0,
            "fired_losses":  fired_losses or 0,
            "times_fired":   times_fired or 0,
            "sample_size":   fired_total,
        }

    if not results:
        print(f"\n[INFO] No signals with ≥{min_samples} samples yet.")
        return {}

    if _HAS_RICH:
        table = Table(title="Signal Accuracy Report", box=box.ROUNDED, header_style="bold cyan")
        table.add_column("Signal", width=22)
        table.add_column("Accuracy", justify="center", width=10)
        table.add_column("Wins", justify="center", width=6)
        table.add_column("Losses", justify="center", width=8)
        table.add_column("Samples", justify="center", width=8)
        table.add_column("Assessment", width=22)

        for sig, d in sorted(results.items(), key=lambda x: -x[1]["accuracy_pct"]):
            acc = d["accuracy_pct"]
            if acc >= 65:
                col = "green"
                assessment = "Reliable — upweight"
            elif acc >= 50:
                col = "yellow"
                assessment = "Average"
            elif acc >= 35:
                col = "orange3"
                assessment = "Weak — review"
            else:
                col = "red"
                assessment = "Unreliable — downweight"

            table.add_row(
                sig,
                f"[{col}]{acc:.1f}%[/{col}]",
                str(d["fired_wins"]),
                str(d["fired_losses"]),
                str(d["sample_size"]),
                f"[{col}]{assessment}[/{col}]",
            )
        _console.print()
        _console.print(table)
    else:
        print("\nSignal Accuracy Report:")
        print(f"{'Signal':<25} {'Accuracy':>10} {'Wins':>6} {'Losses':>8} {'Samples':>8}")
        print("-" * 65)
        for sig, d in sorted(results.items(), key=lambda x: -x[1]["accuracy_pct"]):
            print(f"{sig:<25} {d['accuracy_pct']:>9.1f}% {d['fired_wins']:>6} {d['fired_losses']:>8} {d['sample_size']:>8}")

    print(f"\nRun 'python tools/adjust_weights.py' to apply these accuracy scores to signal weights.")
    return results


def main():
    parser = argparse.ArgumentParser(description="Audit signal accuracy from trade history")
    parser.add_argument("--min-samples", type=int, default=1,
                        help="Minimum number of times a signal must have fired to be included")
    args = parser.parse_args()
    analyze_errors(args.min_samples)


if __name__ == "__main__":
    main()

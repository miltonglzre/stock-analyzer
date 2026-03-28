"""
adjust_weights.py — Recalculate signal weights from trade history and save to weights.json.

Uses bounded exponential moving average update:
    new_weight = old_weight * (1 - lr) + accuracy * lr
    clamped to [0.2, 2.0]

Learning rate decays from LEARNING_RATE_INITIAL to LEARNING_RATE_STABLE once
a signal has been observed >= LEARNING_RATE_THRESHOLD times.

Usage:
    python tools/adjust_weights.py
"""

import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path, weights_path, load_json, save_json, get_float, get_int, DEFAULT_WEIGHTS


def adjust_weights() -> dict:
    db = db_path()
    if not db.exists():
        print("[ERROR] Database not found. Run: python tools/db_init.py")
        sys.exit(1)

    lr_initial = get_float("LEARNING_RATE_INITIAL", 0.3)
    lr_stable = get_float("LEARNING_RATE_STABLE", 0.1)
    lr_threshold = get_int("LEARNING_RATE_THRESHOLD", 20)
    weight_min = 0.2
    weight_max = 2.0

    # Load current weights
    wp = weights_path()
    current_weights_raw = load_json(wp)
    current_weights = {k: float(current_weights_raw.get(k, 1.0)) for k in DEFAULT_WEIGHTS}

    # Query signal accuracy from closed trades
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("""
            SELECT
                ts.signal_type,
                SUM(CASE WHEN ts.signal_fired = 1 AND t.outcome = 'win' THEN 1 ELSE 0 END)  AS fired_wins,
                SUM(CASE WHEN ts.signal_fired = 1 AND t.outcome = 'loss' THEN 1 ELSE 0 END) AS fired_losses,
                SUM(ts.signal_fired) AS times_fired
            FROM trade_signals ts
            JOIN trades t ON ts.trade_id = t.id
            WHERE t.outcome IS NOT NULL
            GROUP BY ts.signal_type
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        print("[INFO] No closed trades yet. Weights unchanged.")
        return current_weights

    new_weights = dict(current_weights)
    updates = []

    for row in rows:
        signal_type, fired_wins, fired_losses, times_fired = row
        fired_wins = fired_wins or 0
        fired_losses = fired_losses or 0
        fired_total = fired_wins + fired_losses

        if fired_total == 0 or signal_type not in DEFAULT_WEIGHTS:
            continue

        accuracy = fired_wins / fired_total  # 0.0 to 1.0

        # Learning rate decays with sample size
        lr = lr_stable if times_fired >= lr_threshold else lr_initial

        old_weight = current_weights.get(signal_type, 1.0)
        # Map accuracy 0-1 to weight scale 0.2-2.0:
        # accuracy=0.5 → target_weight=1.0 (no change baseline)
        # accuracy=1.0 → target_weight=2.0 (double)
        # accuracy=0.0 → target_weight=0.2 (floor)
        target_weight = 0.2 + accuracy * 1.8  # linear mapping
        new_weight = old_weight * (1 - lr) + target_weight * lr
        new_weight = round(max(weight_min, min(weight_max, new_weight)), 4)
        new_weights[signal_type] = new_weight

        updates.append({
            "signal_type":  signal_type,
            "old_weight":   round(old_weight, 4),
            "new_weight":   new_weight,
            "accuracy_pct": round(accuracy * 100, 1),
            "sample_size":  fired_total,
            "lr_used":      lr,
        })

    # Save updated weights
    weights_to_save = {**new_weights, "last_updated": datetime.now().isoformat()}
    wp.parent.mkdir(parents=True, exist_ok=True)
    with open(wp, "w") as f:
        json.dump(weights_to_save, f, indent=2)

    # Save to weight_history in DB
    db_conn = sqlite3.connect(db)
    try:
        for u in updates:
            db_conn.execute("""
                INSERT INTO weight_history (signal_type, weight, sample_size, accuracy_pct)
                VALUES (?,?,?,?)
            """, (u["signal_type"], u["new_weight"], u["sample_size"], u["accuracy_pct"]))
        db_conn.commit()
    finally:
        db_conn.close()

    # Print summary
    if updates:
        print("\n=== Weight Updates ===")
        print(f"{'Signal':<25} {'Old':>8} {'New':>8} {'Accuracy':>10} {'Samples':>8}")
        print("-" * 65)
        for u in sorted(updates, key=lambda x: -x["accuracy_pct"]):
            arrow = "↑" if u["new_weight"] > u["old_weight"] else "↓" if u["new_weight"] < u["old_weight"] else "="
            print(f"{u['signal_type']:<25} {u['old_weight']:>8.3f} {u['new_weight']:>8.3f} {u['accuracy_pct']:>9.1f}% {u['sample_size']:>8} {arrow}")
        print(f"\nWeights saved to: {wp}")
    else:
        print("[INFO] No updates were made.")

    return new_weights


if __name__ == "__main__":
    adjust_weights()

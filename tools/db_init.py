"""
db_init.py — Create / migrate the SQLite schema for the trading platform.

Usage:
    python tools/db_init.py
"""

import sqlite3
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).parent))
from utils import db_path

SCHEMA = """
-- ── Primary trade log ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    entry_date      TEXT    NOT NULL,
    entry_price     REAL    NOT NULL,
    exit_date       TEXT,
    exit_price      REAL,
    pnl_pct         REAL,
    outcome         TEXT,           -- 'win' | 'loss' | 'neutral'
    recommendation  TEXT    NOT NULL,
    confidence_pct  INTEGER NOT NULL,
    verdict         TEXT    NOT NULL,
    notes           TEXT,
    is_paper        INTEGER NOT NULL DEFAULT 0,   -- 1 = auto paper trade
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ── Signals that fired for each trade ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    signal_type     TEXT    NOT NULL,
    signal_value    REAL,
    signal_fired    INTEGER NOT NULL,   -- 1 = fired, 0 = not fired
    signal_direction TEXT   NOT NULL    -- 'bullish' | 'bearish'
);

-- ── Historical weight snapshots ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS weight_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_type     TEXT    NOT NULL,
    weight          REAL    NOT NULL,
    sample_size     INTEGER NOT NULL,
    accuracy_pct    REAL    NOT NULL,
    recorded_at     TEXT    DEFAULT (datetime('now'))
);

-- ── Full analysis reports ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analysis_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    run_date        TEXT    NOT NULL,
    fundamentals_rating TEXT,
    news_sentiment  TEXT,
    verdict         TEXT,
    confidence_pct  INTEGER,
    recommendation  TEXT,
    entry_zone_low  REAL,
    entry_zone_high REAL,
    stop_loss       REAL,
    target_price    REAL,
    full_report_json TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_trades_ticker      ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_outcome     ON trades(outcome);
CREATE INDEX IF NOT EXISTS idx_signals_trade_id   ON trade_signals(trade_id);
CREATE INDEX IF NOT EXISTS idx_signals_type       ON trade_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_reports_ticker     ON analysis_reports(ticker);
"""


def init_db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # Migrate existing DBs: add is_paper column if missing
    try:
        conn.execute("ALTER TABLE trades ADD COLUMN is_paper INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()
    print(f"[OK] Database initialized at: {path}")


if __name__ == "__main__":
    init_db()

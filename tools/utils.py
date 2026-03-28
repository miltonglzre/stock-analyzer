"""
utils.py — Shared helpers for the stock analysis platform.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (two levels up from tools/)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")


# ── Path helpers ──────────────────────────────────────────────────────────────

def tmp_path(ticker: str, module: str) -> Path:
    """Return the .tmp path for a given ticker + module JSON."""
    out_dir = _ROOT / os.getenv("OUTPUT_DIR", ".tmp")
    out_dir.mkdir(exist_ok=True)
    return out_dir / f"{ticker.upper()}_{module}.json"


def db_path() -> Path:
    return _ROOT / os.getenv("DB_PATH", "data/trades.db")


def weights_path() -> Path:
    return _ROOT / os.getenv("WEIGHTS_PATH", "data/weights.json")


# ── JSON helpers ──────────────────────────────────────────────────────────────

def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Env helpers ───────────────────────────────────────────────────────────────

def get_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


def get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


# ── Default signal weights ────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "rsi_oversold":        1.0,
    "rsi_overbought":      1.0,
    "ma_golden_cross":     1.0,
    "ma_death_cross":      1.0,
    "macd_bullish":        1.0,
    "macd_bearish":        1.0,
    "fundamentals_strong": 1.0,
    "fundamentals_weak":   1.0,
    "news_bullish":        1.0,
    "news_bearish":        1.0,
    "support_bounce":      1.0,
    "resistance_hit":      1.0,
}


def load_weights() -> dict:
    """Load current signal weights, falling back to defaults for missing keys."""
    path = weights_path()
    saved = load_json(path)
    weights = {**DEFAULT_WEIGHTS}
    for k, v in saved.items():
        if k in weights:
            weights[k] = float(v)
    return weights

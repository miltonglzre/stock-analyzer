"""
fetch_fundamentals.py — Fetch and evaluate financial fundamentals via yfinance.

Produces a rating: Strong / Neutral / Weak and a score from -1.0 to +1.0.

Output: .tmp/{TICKER}_fundamentals.json

Usage:
    python tools/fetch_fundamentals.py AAPL
"""

import sys
import yfinance as yf
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json


def _safe(val):
    """Return None if value is NaN or None, else return the value."""
    try:
        if val is None:
            return None
        if pd.isna(val):
            return None
        return val
    except Exception:
        return val


def _revenue_growth(financials: pd.DataFrame) -> float | None:
    """Calculate YoY revenue growth from the income statement."""
    if financials is None or financials.empty:
        return None
    try:
        rev_row = None
        for label in ["Total Revenue", "Revenue"]:
            if label in financials.index:
                rev_row = financials.loc[label]
                break
        if rev_row is None or len(rev_row) < 2:
            return None
        latest = rev_row.iloc[0]
        prev = rev_row.iloc[1]
        if prev and prev != 0:
            return round((latest - prev) / abs(prev) * 100, 2)
    except Exception:
        pass
    return None


def _score_fundamentals(metrics: dict) -> tuple[str, float, list[str]]:
    """
    Score the fundamentals from -1.0 (Weak) to +1.0 (Strong).
    Returns (rating, score, reasons).
    """
    points = 0
    max_points = 0
    reasons = []

    # ── P/E Ratio ─────────────────────────────────────────────────────────────
    pe = metrics.get("pe_ratio")
    if pe is not None:
        max_points += 2
        if 0 < pe < 15:
            points += 2
            reasons.append(f"P/E {pe:.1f} — very low, undervalued signal")
        elif 15 <= pe < 25:
            points += 1
            reasons.append(f"P/E {pe:.1f} — fair valuation range")
        elif pe >= 40:
            points -= 1
            reasons.append(f"P/E {pe:.1f} — high valuation, growth priced in")
        elif pe < 0:
            points -= 1
            reasons.append(f"P/E {pe:.1f} — negative earnings")

    # ── EPS ───────────────────────────────────────────────────────────────────
    eps = metrics.get("eps")
    if eps is not None:
        max_points += 1
        if eps > 0:
            points += 1
            reasons.append(f"EPS ${eps:.2f} — profitable")
        else:
            points -= 1
            reasons.append(f"EPS ${eps:.2f} — not yet profitable")

    # ── Revenue Growth ────────────────────────────────────────────────────────
    rev_growth = metrics.get("revenue_growth_yoy")
    if rev_growth is not None:
        max_points += 2
        if rev_growth >= 20:
            points += 2
            reasons.append(f"Revenue growth {rev_growth:.1f}% YoY — strong expansion")
        elif rev_growth >= 5:
            points += 1
            reasons.append(f"Revenue growth {rev_growth:.1f}% YoY — moderate growth")
        elif rev_growth < 0:
            points -= 1
            reasons.append(f"Revenue growth {rev_growth:.1f}% YoY — contracting")

    # ── Profit Margin ─────────────────────────────────────────────────────────
    margin = metrics.get("profit_margin")
    if margin is not None:
        max_points += 1
        if margin >= 0.15:
            points += 1
            reasons.append(f"Profit margin {margin*100:.1f}% — healthy")
        elif margin < 0:
            points -= 1
            reasons.append(f"Profit margin {margin*100:.1f}% — unprofitable")

    # ── Debt-to-Equity ────────────────────────────────────────────────────────
    de = metrics.get("debt_to_equity")
    if de is not None:
        max_points += 1
        if de < 0.5:
            points += 1
            reasons.append(f"D/E ratio {de:.2f} — low leverage")
        elif de > 2.0:
            points -= 1
            reasons.append(f"D/E ratio {de:.2f} — high leverage")

    # ── Return on Equity ──────────────────────────────────────────────────────
    roe = metrics.get("return_on_equity")
    if roe is not None:
        max_points += 1
        if roe >= 0.15:
            points += 1
            reasons.append(f"ROE {roe*100:.1f}% — efficient capital use")
        elif roe < 0:
            points -= 1
            reasons.append(f"ROE {roe*100:.1f}% — destroying value")

    if max_points == 0:
        return ("Neutral", 0.0, ["Insufficient data for scoring"])

    score = round(points / max_points, 4)
    score = max(-1.0, min(1.0, score))

    if score >= 0.4:
        rating = "Strong"
    elif score <= -0.2:
        rating = "Weak"
    else:
        rating = "Neutral"

    return (rating, score, reasons)


def fetch_fundamentals(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info

    try:
        fin = t.financials
    except Exception:
        fin = None

    metrics = {
        "ticker":             ticker.upper(),
        "pe_ratio":           _safe(info.get("trailingPE") or info.get("forwardPE")),
        "eps":                _safe(info.get("trailingEps")),
        "market_cap":         _safe(info.get("marketCap")),
        "revenue_ttm":        _safe(info.get("totalRevenue")),
        "net_income_ttm":     _safe(info.get("netIncomeToCommon")),
        "profit_margin":      _safe(info.get("profitMargins")),
        "gross_margin":       _safe(info.get("grossMargins")),
        "operating_margin":   _safe(info.get("operatingMargins")),
        "debt_to_equity":     _safe(info.get("debtToEquity")),
        "return_on_equity":   _safe(info.get("returnOnEquity")),
        "return_on_assets":   _safe(info.get("returnOnAssets")),
        "current_ratio":      _safe(info.get("currentRatio")),
        "quick_ratio":        _safe(info.get("quickRatio")),
        "revenue_growth_yoy": _revenue_growth(fin),
        "dividend_yield":     _safe(info.get("dividendYield")),
        "beta":               _safe(info.get("beta")),
        "book_value":         _safe(info.get("bookValue")),
        "price_to_book":      _safe(info.get("priceToBook")),
    }

    # Normalize D/E (yfinance returns it × 100 sometimes)
    de = metrics["debt_to_equity"]
    if de is not None and de > 20:
        metrics["debt_to_equity"] = round(de / 100, 4)

    rating, score, reasons = _score_fundamentals(metrics)
    metrics["rating"] = rating
    metrics["score"] = score
    metrics["reasoning"] = reasons

    path = tmp_path(ticker, "fundamentals")
    save_json(path, metrics)
    print(f"[OK] Fundamentals ({rating}, score={score:.2f}) saved -> {path}")
    return metrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_fundamentals.py <TICKER>")
        sys.exit(1)
    fetch_fundamentals(sys.argv[1].upper())

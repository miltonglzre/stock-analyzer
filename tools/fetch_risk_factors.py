"""
fetch_risk_factors.py — Evaluate risk factors for a stock.

Factors analyzed:
  - Beta (market volatility exposure)
  - Short interest ratio
  - Debt levels (D/E, current ratio)
  - Insider selling activity
  - Sector/macro headwinds (qualitative flags)

Output: .tmp/{TICKER}_risks.json

Usage:
    python tools/fetch_risk_factors.py AAPL
"""

import sys
import yfinance as yf
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json


def _score_risks(info: dict) -> tuple[float, list[str]]:
    """
    Returns penalty score: 0.0 (no risk) to -1.0 (high risk) and reasons.
    """
    penalty = 0.0
    reasons = []

    # ── Beta ──────────────────────────────────────────────────────────────────
    beta = info.get("beta")
    if beta is not None:
        if beta > 2.0:
            penalty -= 0.25
            reasons.append(f"Beta {beta:.2f} — very high volatility vs market")
        elif beta > 1.5:
            penalty -= 0.15
            reasons.append(f"Beta {beta:.2f} — above-average market volatility")
        elif beta < 0:
            penalty -= 0.10
            reasons.append(f"Beta {beta:.2f} — negative correlation with market (unusual)")
        else:
            reasons.append(f"Beta {beta:.2f} — within acceptable volatility range")

    # ── Short Interest ─────────────────────────────────────────────────────────
    short_ratio = info.get("shortRatio")  # days to cover
    short_pct = info.get("shortPercentOfFloat")
    if short_ratio is not None:
        if short_ratio > 10:
            penalty -= 0.25
            reasons.append(f"Short ratio {short_ratio:.1f} days — heavily shorted (bearish pressure)")
        elif short_ratio > 5:
            penalty -= 0.10
            reasons.append(f"Short ratio {short_ratio:.1f} days — elevated short interest")
        else:
            reasons.append(f"Short ratio {short_ratio:.1f} days — low short interest")
    if short_pct is not None:
        if short_pct > 0.20:
            penalty -= 0.15
            reasons.append(f"Short float {short_pct*100:.1f}% — significant short position")

    # ── Debt Load ─────────────────────────────────────────────────────────────
    de = info.get("debtToEquity")
    if de is not None:
        if de > 200:
            de = de / 100  # normalize if yfinance returned × 100
        if de > 3.0:
            penalty -= 0.20
            reasons.append(f"D/E ratio {de:.2f} — very high leverage")
        elif de > 1.5:
            penalty -= 0.10
            reasons.append(f"D/E ratio {de:.2f} — elevated debt levels")

    current_ratio = info.get("currentRatio")
    if current_ratio is not None:
        if current_ratio < 1.0:
            penalty -= 0.15
            reasons.append(f"Current ratio {current_ratio:.2f} — potential liquidity risk")
        elif current_ratio < 1.5:
            penalty -= 0.05
            reasons.append(f"Current ratio {current_ratio:.2f} — adequate but watch liquidity")

    # ── Insider Activity ──────────────────────────────────────────────────────
    # yfinance doesn't expose a direct insider net buy/sell ratio,
    # but we can check heldPercentInsiders as a proxy for alignment.
    held_insiders = info.get("heldPercentInsiders")
    if held_insiders is not None:
        if held_insiders < 0.01:
            penalty -= 0.10
            reasons.append(f"Insider ownership {held_insiders*100:.1f}% — very low insider stake")
        elif held_insiders > 0.20:
            reasons.append(f"Insider ownership {held_insiders*100:.1f}% — strong insider alignment")

    # ── Revenue Decline ───────────────────────────────────────────────────────
    rev_growth = info.get("revenueGrowth")
    if rev_growth is not None and rev_growth < -0.10:
        penalty -= 0.15
        reasons.append(f"Revenue declining {rev_growth*100:.1f}% — deteriorating business")

    # ── Profit Margins ────────────────────────────────────────────────────────
    margin = info.get("profitMargins")
    if margin is not None and margin < 0:
        penalty -= 0.10
        reasons.append(f"Negative profit margin ({margin*100:.1f}%) — burning cash")

    # Clamp to [-1.0, 0.0]
    penalty = max(-1.0, penalty)

    if not reasons:
        reasons.append("No significant risk flags detected")

    if penalty <= -0.5:
        level = "High"
    elif penalty <= -0.2:
        level = "Moderate"
    else:
        level = "Low"

    return penalty, level, reasons


def fetch_risk_factors(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info

    penalty, level, reasons = _score_risks(info)

    data = {
        "ticker":            ticker.upper(),
        "risk_level":        level,
        "score":             round(penalty, 4),
        "beta":              info.get("beta"),
        "short_ratio":       info.get("shortRatio"),
        "short_pct_float":   info.get("shortPercentOfFloat"),
        "debt_to_equity":    info.get("debtToEquity"),
        "current_ratio":     info.get("currentRatio"),
        "insider_ownership": info.get("heldPercentInsiders"),
        "institutional_pct": info.get("heldPercentInstitutions"),
        "revenue_growth":    info.get("revenueGrowth"),
        "profit_margin":     info.get("profitMargins"),
        "reasoning":         reasons,
    }

    path = tmp_path(ticker, "risks")
    save_json(path, data)
    print(f"[OK] Risk factors ({level}, penalty={penalty:.2f}) saved -> {path}")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_risk_factors.py <TICKER>")
        sys.exit(1)
    fetch_risk_factors(sys.argv[1].upper())

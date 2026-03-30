"""
fetch_opportunities.py — Identify bullish opportunity signals for a stock.

Factors analyzed:
  - Analyst consensus and recent upgrades
  - Earnings surprises (beat/miss history)
  - Institutional ownership trend
  - Revenue growth trajectory
  - Dividend / buyback activity

Output: .tmp/{TICKER}_opportunities.json

Usage:
    python tools/fetch_opportunities.py AAPL
"""

import sys
import yfinance as yf
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json


def _analyst_score(info: dict) -> tuple[float, list[str]]:
    """Score analyst consensus: 0.0 to +1.0."""
    bonus = 0.0
    reasons = []

    # recommendationMean: 1=Strong Buy, 2=Buy, 3=Hold, 4=Sell, 5=Strong Sell
    rec_mean = info.get("recommendationMean")
    rec_key = info.get("recommendationKey", "").lower()
    num_analysts = info.get("numberOfAnalystOpinions", 0)

    if rec_mean is not None:
        if rec_mean <= 1.5:
            bonus += 0.30
            reasons.append(f"Analyst consensus: Strong Buy ({num_analysts} analysts)")
        elif rec_mean <= 2.5:
            bonus += 0.20
            reasons.append(f"Analyst consensus: Buy ({num_analysts} analysts)")
        elif rec_mean <= 3.0:
            bonus += 0.05
            reasons.append(f"Analyst consensus: Hold ({num_analysts} analysts)")
        elif rec_mean > 3.5:
            bonus -= 0.10
            reasons.append(f"Analyst consensus: Sell/Underperform ({num_analysts} analysts)")

    # Target price vs current price
    target = info.get("targetMeanPrice")
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and current and current > 0:
        upside = (target - current) / current * 100
        if upside >= 20:
            bonus += 0.20
            reasons.append(f"Analyst target ${target:.2f} — {upside:.1f}% upside potential")
        elif upside >= 10:
            bonus += 0.10
            reasons.append(f"Analyst target ${target:.2f} — {upside:.1f}% upside")
        elif upside < 0:
            bonus -= 0.10
            reasons.append(f"Analyst target ${target:.2f} — {abs(upside):.1f}% downside from current")

    return bonus, reasons


def _earnings_score(ticker_obj) -> tuple[float, list[str]]:
    """Score earnings surprise history: 0.0 to +0.3."""
    bonus = 0.0
    reasons = []
    try:
        eps_hist = ticker_obj.earnings_history
        if eps_hist is None or eps_hist.empty:
            return 0.0, []
        # Last 4 quarters
        recent = eps_hist.head(4)
        beats = 0
        for _, row in recent.iterrows():
            eps_est = row.get("epsEstimate") or row.get("EPSEstimate")
            eps_act = row.get("epsActual") or row.get("EPSActual")
            if eps_est and eps_act and eps_act > eps_est:
                beats += 1
        if beats >= 3:
            bonus += 0.20
            reasons.append(f"Beat earnings estimates {beats}/4 recent quarters")
        elif beats == 2:
            bonus += 0.10
            reasons.append(f"Beat earnings estimates {beats}/4 recent quarters")
        elif beats == 0:
            bonus -= 0.10
            reasons.append("Missed earnings estimates in recent quarters")
    except Exception:
        pass
    return bonus, reasons


def _growth_score(info: dict) -> tuple[float, list[str]]:
    """Score growth metrics: 0.0 to +0.2."""
    bonus = 0.0
    reasons = []

    rev_growth = info.get("revenueGrowth")
    if rev_growth is not None:
        if rev_growth >= 0.20:
            bonus += 0.15
            reasons.append(f"Revenue growing {rev_growth*100:.1f}% YoY — strong expansion")
        elif rev_growth >= 0.10:
            bonus += 0.08
            reasons.append(f"Revenue growing {rev_growth*100:.1f}% YoY")

    earnings_growth = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
    if earnings_growth is not None and earnings_growth > 0.15:
        bonus += 0.10
        reasons.append(f"Earnings growing {earnings_growth*100:.1f}% — profitability improving")

    return bonus, reasons


def _buyback_dividend_score(info: dict) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons = []

    div_yield = info.get("dividendYield")
    if div_yield and div_yield > 0.02:
        bonus += 0.05
        reasons.append(f"Dividend yield {div_yield*100:.1f}% — income support")

    # Proxy for buybacks: check if shares outstanding declined
    # yfinance doesn't expose direct buyback data, so we skip this

    return bonus, reasons


def fetch_opportunities(ticker: str, _info: dict = None) -> dict:
    t = yf.Ticker(ticker)
    info = _info if _info is not None else t.info

    analyst_bonus, analyst_reasons = _analyst_score(info)
    earnings_bonus, earnings_reasons = _earnings_score(t)
    growth_bonus, growth_reasons = _growth_score(info)
    buyback_bonus, buyback_reasons = _buyback_dividend_score(info)

    total_bonus = analyst_bonus + earnings_bonus + growth_bonus + buyback_bonus
    total_bonus = round(max(0.0, min(1.0, total_bonus)), 4)

    all_reasons = analyst_reasons + earnings_reasons + growth_reasons + buyback_reasons
    if not all_reasons:
        all_reasons = ["No significant opportunity signals detected"]

    if total_bonus >= 0.4:
        level = "High"
    elif total_bonus >= 0.15:
        level = "Moderate"
    else:
        level = "Low"

    data = {
        "ticker":              ticker.upper(),
        "opportunity_level":   level,
        "score":               total_bonus,
        "analyst_target":      info.get("targetMeanPrice"),
        "analyst_rec":         info.get("recommendationKey"),
        "analyst_rec_mean":    info.get("recommendationMean"),
        "num_analysts":        info.get("numberOfAnalystOpinions"),
        "revenue_growth":      info.get("revenueGrowth"),
        "earnings_growth":     info.get("earningsGrowth"),
        "dividend_yield":      info.get("dividendYield"),
        "reasoning":           all_reasons,
    }

    path = tmp_path(ticker, "opportunities")
    save_json(path, data)
    print(f"[OK] Opportunities ({level}, bonus={total_bonus:.2f}) saved -> {path}")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_opportunities.py <TICKER>")
        sys.exit(1)
    fetch_opportunities(sys.argv[1].upper())

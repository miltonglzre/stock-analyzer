"""
fetch_company_overview.py — Fetch company profile data via yfinance.

Output: .tmp/{TICKER}_overview.json

Usage:
    python tools/fetch_company_overview.py AAPL
"""

import sys
import yfinance as yf
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import tmp_path, save_json


def fetch_company_overview(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        # Try a lightweight check — some tickers return minimal info
        if not info.get("shortName") and not info.get("longName"):
            print(f"[ERROR] Ticker '{ticker}' not found or no data available.")
            sys.exit(1)

    data = {
        "ticker":             ticker.upper(),
        "name":               info.get("longName") or info.get("shortName", "N/A"),
        "sector":             info.get("sector", "N/A"),
        "industry":           info.get("industry", "N/A"),
        "country":            info.get("country", "N/A"),
        "exchange":           info.get("exchange", "N/A"),
        "market_cap":         info.get("marketCap"),
        "employees":          info.get("fullTimeEmployees"),
        "website":            info.get("website", "N/A"),
        "description":        info.get("longBusinessSummary", "No description available."),
        "currency":           info.get("currency", "USD"),
        "current_price":      info.get("currentPrice") or info.get("regularMarketPrice"),
        "52w_high":           info.get("fiftyTwoWeekHigh"),
        "52w_low":            info.get("fiftyTwoWeekLow"),
        "prev_close":         info.get("previousClose") or info.get("regularMarketPreviousClose"),
        "pre_market_price":   info.get("preMarketPrice"),
        "post_market_price":  info.get("postMarketPrice"),
    }

    path = tmp_path(ticker, "overview")
    save_json(path, data)
    print(f"[OK] Company overview saved -> {path}")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/fetch_company_overview.py <TICKER>")
        sys.exit(1)
    fetch_company_overview(sys.argv[1].upper())

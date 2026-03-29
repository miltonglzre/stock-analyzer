"""
watchlist.py — Curated stock universe for the market scanner.

~75 liquid, high-volume tickers organized by sector.
All have >$1B market cap and >500K avg daily volume.
"""

WATCHLIST = {
    "Technology": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
        "AMD", "INTC", "CRM", "ORCL", "ADBE", "QCOM", "AVGO", "MU",
        "PLTR", "SNOW", "NET", "UBER", "COIN",
    ],
    "Finance": [
        "JPM", "BAC", "GS", "MS", "WFC", "V", "MA", "AXP",
        "BLK", "SCHW", "C", "BRK-B",
    ],
    "Healthcare": [
        "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO",
        "CVS", "MDT", "AMGN", "GILD", "BMY",
    ],
    "Energy": [
        "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "VLO",
    ],
    "Consumer": [
        "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT",
        "LOW", "DIS", "NFLX", "ABNB",
    ],
    "ETFs": [
        "SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "GLD", "ARKK", "SOXL",
    ],
}

# Flat list for batch downloads
ALL_TICKERS = [t for sector_tickers in WATCHLIST.values() for t in sector_tickers]

# Reverse map: ticker -> sector
TICKER_SECTOR = {
    t: sector
    for sector, tickers in WATCHLIST.items()
    for t in tickers
}


def get_sector(ticker: str) -> str:
    return TICKER_SECTOR.get(ticker.upper(), "Other")

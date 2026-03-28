# Workflow: Stock Analysis

## Objective
Produce a complete Buy / Wait / Sell recommendation for any US stock ticker,
with confidence score, entry zone, stop-loss, and target price.

## Required Inputs
- `TICKER`: US stock symbol (e.g. `AAPL`, `TSLA`, `NVDA`)

## Tools Used (in order)
1. `tools/fetch_company_overview.py TICKER`
2. `tools/fetch_fundamentals.py TICKER`
3. `tools/fetch_news.py TICKER`
4. `tools/fetch_technicals.py TICKER`
5. `tools/fetch_risk_factors.py TICKER`
6. `tools/fetch_opportunities.py TICKER`
7. `tools/decision_engine.py TICKER`

Or run all in one command:
```bash
python tools/stock_analyzer.py TICKER
```

## Steps
1. Run `stock_analyzer.py TICKER` — it executes all tools in sequence.
2. Each tool writes its output to `.tmp/{TICKER}_{module}.json`.
3. `decision_engine.py` reads all `.tmp/` files and calculates the weighted verdict.
4. The report is printed to the terminal and saved to `analysis_reports` in SQLite.

## Expected Output
A terminal report with:
- Company description and market position
- Fundamentals rating: **Strong / Neutral / Weak**
- News sentiment: **Bullish / Neutral / Bearish** + key events
- Technical indicators: RSI, MACD, SMA crossovers, support/resistance
- Risk flags and opportunity signals
- **Final verdict**: Bullish / Neutral / Bearish
- **Confidence**: 0–100%
- **Recommendation**: Buy / Wait / Sell
- **Timing**: Entry zone, stop-loss, target price

## Edge Cases & Known Issues
- **Ticker not found**: yfinance returns empty data → tool exits with error. Verify ticker on finance.yahoo.com.
- **No news found**: yfinance returns 0 articles → falls back to Google News RSS. If RSS also empty, news score = 0 (Neutral).
- **Insufficient price history** (< 30 days): fetch_technicals fails. Only applies to very new listings.
- **Market closed / weekend**: Price data is the last close. Technicals still valid, note timing.
- **Missing pandas-ta**: Falls back to manual RSI/MACD calculation. Results are equivalent.

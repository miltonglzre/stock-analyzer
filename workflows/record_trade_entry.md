# Workflow: Record Trade Entry

## Objective
Log a new position in the learning system so it can be tracked, closed, and
used to improve future signal weights.

## Required Inputs
- `TICKER`: stock symbol
- `ENTRY_PRICE`: price actually paid (not the suggested entry zone)
- `RECOMMENDATION`: `Buy`, `Sell`, or `Wait`

## Prerequisite
Run the stock analysis workflow first so `.tmp/{TICKER}_decision.json` exists.
The recorder reads this file to auto-populate signals — no need to specify them manually.

## Tool Used
```bash
python tools/record_trade.py TICKER ENTRY_PRICE RECOMMENDATION
python tools/record_trade.py AAPL 175.40 Buy
python tools/record_trade.py TSLA 250.00 Sell --notes "Overvalued after Q3 earnings"
```

## Steps
1. Run `stock_analyzer.py TICKER` to get the recommendation.
2. Decide whether to act on the recommendation.
3. Run `record_trade.py` with your actual entry price.
4. Note the Trade ID printed to the terminal — you need it to close the trade.

## Expected Output
```
[OK] Trade #7 recorded: Buy AAPL @ $175.40
     Verdict: Bullish (72% confidence)
     Signals recorded: 4 active

     When you close this position, run:
     python tools/record_outcome.py 7 <exit_price>
```

## Edge Cases
- **No analysis found for ticker**: Run `stock_analyzer.py TICKER` first.
- **Entering against the recommendation**: Allowed. The `recommendation` field
  accepts any of Buy/Sell/Wait regardless of what the system suggested.
  This lets you track contrarian decisions too.

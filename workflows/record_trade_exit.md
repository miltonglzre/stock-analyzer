# Workflow: Record Trade Exit

## Objective
Close an open trade, calculate P&L, and classify it as win / loss / neutral
for the learning system.

## Required Inputs
- `TRADE_ID`: integer printed when the trade was entered (see record_trade_entry workflow)
- `EXIT_PRICE`: actual price at which the position was closed

## Classification Thresholds (configurable in .env)
- **Win**: P&L ≥ +5.0%
- **Loss**: P&L ≤ −5.0%
- **Neutral**: between −5% and +5%

## Tool Used
```bash
python tools/record_outcome.py TRADE_ID EXIT_PRICE
python tools/record_outcome.py 7 183.20
python tools/record_outcome.py 7 183.20 --notes "Hit target, took profit"
```

## Steps
1. Find the Trade ID from when you opened the position.
2. Run `record_outcome.py` with the actual exit price.
3. The system updates the trade record and prints the P&L.
4. After 5+ closed trades, run the learning cycle to update weights.

## Expected Output
```
[OK] Trade #7 (AAPL) closed → [WIN] P&L: +4.46%
     Entry: $175.40  Exit: $183.20

Run the learning cycle to update signal weights:
  python tools/analyze_errors.py
  python tools/adjust_weights.py
```

## Edge Cases
- **Trade ID not found**: Check `data/trades.db` or re-run listing.
- **Closing at a loss**: Enter the actual exit price — no special handling needed.
- **Partial close**: Record the full exit for simplicity. Note partial size in `--notes`.
- **Already closed trade**: Tool warns but allows overwrite (useful for corrections).

# Workflow: Run Learning Cycle

## Objective
Recalculate signal weights based on closed trade history so future analyses
are informed by actual historical performance rather than default values.

## When to Run
- After every 5+ newly closed trades
- When win rate drops unexpectedly (signals may need recalibration)
- Periodically (e.g., monthly) to keep weights current

## Minimum Requirement
- At least 1 closed trade (outcome = win/loss/neutral)
- For meaningful weights: 10+ closed trades with mix of wins and losses

## Tools Used
```bash
# Step 1 — audit current signal accuracy
python tools/analyze_errors.py

# Step 2 — update weights.json based on accuracy audit
python tools/adjust_weights.py
```

## Steps
1. Run `analyze_errors.py` to see a table of signal accuracy by type.
2. Review which signals have ≥ 65% accuracy (reliable → upweight)
   and which have < 35% accuracy (unreliable → downweight).
3. Run `adjust_weights.py` to apply the update.
4. The new `data/weights.json` takes effect on the next analysis automatically.

## Expected Output from analyze_errors.py
```
=== Trade Summary ===
  Total closed trades: 18
  Wins: 11  |  Losses: 5  |  Neutral: 2
  Overall win rate: 61.1%

┌──────────────────────────┬──────────┬──────┬────────┬─────────┬──────────────────────────┐
│ Signal                   │ Accuracy │ Wins │ Losses │ Samples │ Assessment               │
├──────────────────────────┼──────────┼──────┼────────┼─────────┼──────────────────────────┤
│ fundamentals_strong      │   78.6%  │   11 │      3 │      14 │ Reliable — upweight      │
│ rsi_oversold             │   70.0%  │    7 │      3 │      10 │ Reliable — upweight      │
│ news_bullish             │   62.5%  │   10 │      6 │      16 │ Average                  │
│ macd_bullish             │   52.4%  │   11 │     10 │      21 │ Average                  │
│ ma_death_cross           │   33.3%  │    3 │      6 │       9 │ Unreliable — downweight  │
└──────────────────────────┴──────────┴──────┴────────┴─────────┴──────────────────────────┘
```

## Expected Output from adjust_weights.py
```
=== Weight Updates ===
Signal                    Old    New   Accuracy  Samples
fundamentals_strong     1.000  1.299    78.6%       14  ↑
rsi_oversold            1.000  1.199    70.0%       10  ↑
news_bullish            1.000  1.025    62.5%       16  ↑
macd_bullish            1.000  0.985    52.4%       21  ↓
ma_death_cross          1.000  0.840    33.3%        9  ↓
```

## Edge Cases
- **All wins**: Weights skew high but are clamped at 2.0. Normal — good performance.
- **All losses**: Weights skew low, clamped at 0.2. Review your entry logic.
- **Signal never fired**: Weight stays at 1.0 (default). No update needed.
- **Fewer than 5 samples per signal**: Results are statistically weak. Tool still runs but treat with caution.
- **Contradictory signals** (e.g., same signal bullish and bearish at different times): Query groups by signal_type so both contribute to the same weight.

## Interpreting Weight History
The `weight_history` table in `data/trades.db` stores every weight update with a timestamp.
To view the full history:
```sql
SELECT signal_type, weight, accuracy_pct, sample_size, recorded_at
FROM weight_history
ORDER BY signal_type, recorded_at;
```

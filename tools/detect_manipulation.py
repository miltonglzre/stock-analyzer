"""
detect_manipulation.py — Flag unusual price/volume patterns that may indicate
market manipulation, short squeezes, pump-and-dumps, or abnormal volatility.

Works entirely from OHLCV data — no paid API needed.
"""

import pandas as pd


def detect_manipulation(ticker: str, hist: pd.DataFrame, info: dict = None) -> list:
    """
    Scan OHLCV history for manipulation signals.

    Args:
        ticker: Ticker symbol (for labeling only)
        hist:   DataFrame with columns Open, High, Low, Close, Volume (at least 10 rows)
        info:   Optional dict with keys like shortPercentOfFloat (from yfinance .info)

    Returns:
        List of flag dicts: {type, severity, detail}
        severity: "high" | "medium" | "low"
    """
    flags = []
    if info is None:
        info = {}

    if hist is None or len(hist) < 5:
        return flags

    try:
        close  = hist["Close"]
        volume = hist["Volume"]
        high   = hist["High"]
        low    = hist["Low"]
        opens  = hist["Open"]

        curr_close  = float(close.iloc[-1])
        curr_open   = float(opens.iloc[-1])
        curr_vol    = float(volume.iloc[-1])
        avg_vol_20  = float(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else float(volume.mean())

        # ── 1. Volume spike ──────────────────────────────────────────────────────
        if avg_vol_20 and avg_vol_20 > 0:
            vol_ratio = curr_vol / avg_vol_20
            if vol_ratio >= 5:
                flags.append({
                    "type": "volume_spike",
                    "severity": "high",
                    "detail": f"Volume {vol_ratio:.1f}x the 20-day avg — extreme unusual activity",
                })
            elif vol_ratio >= 3:
                flags.append({
                    "type": "volume_spike",
                    "severity": "medium",
                    "detail": f"Volume {vol_ratio:.1f}x the 20-day avg — elevated activity",
                })
        else:
            vol_ratio = 1.0

        # ── 2. Intraday candle spike ─────────────────────────────────────────────
        if curr_open and curr_open > 0:
            intraday_pct = ((curr_close - curr_open) / curr_open) * 100
            if abs(intraday_pct) >= 8:
                flags.append({
                    "type": "intraday_spike",
                    "severity": "high",
                    "detail": f"Intraday move {intraday_pct:+.1f}% — extreme single-session volatility",
                })
            elif abs(intraday_pct) >= 4:
                flags.append({
                    "type": "intraday_spike",
                    "severity": "medium",
                    "detail": f"Intraday move {intraday_pct:+.1f}% — notable single-session move",
                })
        else:
            intraday_pct = 0.0

        # ── 3. Gap from previous close ───────────────────────────────────────────
        if len(hist) >= 2:
            prev_close = float(close.iloc[-2])
            if prev_close and prev_close > 0:
                gap_pct = ((curr_open - prev_close) / prev_close) * 100
                direction = "up" if gap_pct > 0 else "down"
                if abs(gap_pct) >= 8:
                    flags.append({
                        "type": f"gap_{direction}",
                        "severity": "high",
                        "detail": f"Gap {direction} {gap_pct:+.1f}% from yesterday's close — possible news event or halt",
                    })
                elif abs(gap_pct) >= 3:
                    flags.append({
                        "type": f"gap_{direction}",
                        "severity": "medium",
                        "detail": f"Gap {direction} {gap_pct:+.1f}% from yesterday's close",
                    })

        # ── 4. Short squeeze signal ──────────────────────────────────────────────
        short_pct = float(info.get("shortPercentOfFloat") or 0)
        if len(hist) >= 2:
            day_change_pct = ((curr_close - float(close.iloc[-2])) / float(close.iloc[-2])) * 100
        else:
            day_change_pct = intraday_pct

        if short_pct >= 0.15 and day_change_pct >= 5 and vol_ratio >= 2:
            flags.append({
                "type": "short_squeeze",
                "severity": "high",
                "detail": (
                    f"Short interest {short_pct:.0%} + price +{day_change_pct:.1f}% "
                    f"+ volume {vol_ratio:.1f}x — potential short squeeze in progress"
                ),
            })
        elif short_pct >= 0.20:
            flags.append({
                "type": "high_short_interest",
                "severity": "medium",
                "detail": f"Short interest {short_pct:.0%} of float — elevated squeeze risk if price moves up",
            })

        # ── 5. Abnormal daily range (ATR spike) ──────────────────────────────────
        if len(hist) >= 20:
            daily_range_pct = ((high - low) / low.replace(0, float("nan"))) * 100
            avg_range = float(daily_range_pct.rolling(20).mean().iloc[-1])
            curr_range = float(daily_range_pct.iloc[-1])
            if avg_range and avg_range > 0 and curr_range >= avg_range * 2.5:
                flags.append({
                    "type": "high_volatility",
                    "severity": "medium",
                    "detail": (
                        f"Daily range {curr_range:.1f}% vs avg {avg_range:.1f}% "
                        f"({curr_range/avg_range:.1f}x normal) — abnormal intraday swings"
                    ),
                })

        # ── 6. Pump pattern: 3+ consecutive up days with rising volume ───────────
        if len(hist) >= 4:
            last_closes = close.iloc[-4:]
            last_vols   = volume.iloc[-4:]
            up_streak     = all(last_closes.diff().dropna() > 0)
            vol_escalating = all(last_vols.diff().dropna() > 0)
            if up_streak and vol_escalating:
                total_move = ((float(last_closes.iloc[-1]) - float(last_closes.iloc[0]))
                              / float(last_closes.iloc[0])) * 100
                if total_move >= 12:
                    flags.append({
                        "type": "pump_pattern",
                        "severity": "high",
                        "detail": (
                            f"3 consecutive up days with escalating volume, "
                            f"total +{total_move:.1f}% — possible pump, trade with caution"
                        ),
                    })

        # ── 7. Dump pattern: 3+ consecutive down days with rising volume ──────────
        if len(hist) >= 4:
            last_closes = close.iloc[-4:]
            last_vols   = volume.iloc[-4:]
            down_streak    = all(last_closes.diff().dropna() < 0)
            vol_escalating = all(last_vols.diff().dropna() > 0)
            if down_streak and vol_escalating:
                total_drop = ((float(last_closes.iloc[-1]) - float(last_closes.iloc[0]))
                              / float(last_closes.iloc[0])) * 100
                if total_drop <= -10:
                    flags.append({
                        "type": "dump_pattern",
                        "severity": "high",
                        "detail": (
                            f"3 consecutive down days with escalating volume, "
                            f"total {total_drop:.1f}% — possible distribution / dump"
                        ),
                    })

    except Exception:
        pass

    return flags

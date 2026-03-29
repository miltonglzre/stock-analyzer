"""
market_hours.py — NYSE market status and trading calendar utilities.

Usage:
    python tools/market_hours.py
"""

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# NYSE official holidays 2025-2026
_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}


def _next_trading_day(from_date: date) -> date:
    d = from_date + timedelta(days=1)
    while d.weekday() >= 5 or d in _HOLIDAYS:
        d += timedelta(days=1)
    return d


def get_market_status() -> dict:
    """
    Returns current NYSE market status.

    Keys:
      is_open         — bool
      status          — "open" | "pre_market" | "post_market" | "weekend" | "holiday"
      message         — human-readable string
      now_et          — datetime in ET
      minutes_to_open — int | None
      minutes_to_close— int | None
    """
    now = datetime.now(ET)
    today = now.date()

    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)

    # Weekend
    if today.weekday() >= 5:
        next_td = _next_trading_day(today)
        next_open = datetime(next_td.year, next_td.month, next_td.day, 9, 30, tzinfo=ET)
        mins = max(0, int((next_open - now).total_seconds() / 60))
        return {
            "is_open": False, "status": "weekend", "now_et": now,
            "message": f"Weekend — NYSE opens {next_td.strftime('%A %b %d')} at 9:30 AM ET",
            "minutes_to_open": mins, "minutes_to_close": None,
        }

    # Holiday
    if today in _HOLIDAYS:
        next_td = _next_trading_day(today)
        return {
            "is_open": False, "status": "holiday", "now_et": now,
            "message": f"NYSE Holiday — next open {next_td.strftime('%A %b %d')}",
            "minutes_to_open": None, "minutes_to_close": None,
        }

    # Pre-market
    if now < market_open:
        mins = int((market_open - now).total_seconds() / 60)
        h, m = divmod(mins, 60)
        return {
            "is_open": False, "status": "pre_market", "now_et": now,
            "message": f"Pre-market — opens in {h}h {m}m (9:30 AM ET)",
            "minutes_to_open": mins, "minutes_to_close": None,
        }

    # Post-market
    if now > market_close:
        next_td = _next_trading_day(today)
        next_open = datetime(next_td.year, next_td.month, next_td.day, 9, 30, tzinfo=ET)
        mins = int((next_open - now).total_seconds() / 60)
        h, m = divmod(mins, 60)
        return {
            "is_open": False, "status": "post_market", "now_et": now,
            "message": f"Post-market — next open {next_td.strftime('%a %b %d')} in {h}h {m}m",
            "minutes_to_open": mins, "minutes_to_close": None,
        }

    # Open
    mins_close = int((market_close - now).total_seconds() / 60)
    h, m = divmod(mins_close, 60)
    return {
        "is_open": True, "status": "open", "now_et": now,
        "message": f"NYSE Open — closes in {h}h {m}m (4:00 PM ET)",
        "minutes_to_open": None, "minutes_to_close": mins_close,
    }


def is_market_open() -> bool:
    return get_market_status()["is_open"]


if __name__ == "__main__":
    s = get_market_status()
    print(f"Status : {s['status']}")
    print(f"Message: {s['message']}")
    print(f"Open   : {s['is_open']}")

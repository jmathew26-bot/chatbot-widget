"""Business-day arithmetic for the follow-up cadence. No holiday calendar
-- just Mon-Fri -- which is good enough for "approximately 5 business
days" per the design doc.
"""
from __future__ import annotations

import datetime as dt


def add_business_days(start: dt.datetime, business_days: int) -> dt.datetime:
    current = start
    remaining = business_days
    while remaining > 0:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return current

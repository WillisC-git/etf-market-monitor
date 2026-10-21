"""V2.3 scheduled read-only monitor. No orders, push, or persistent dedupe.

Uses the previously tested V2.2 analysis and avoids running outside the first
2 hours of regular NYSE trading. A NYSE holiday calendar is required.
"""
import os
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
import monitor_v22

ET = ZoneInfo('America/New_York')


def main():
    now = datetime.now(timezone.utc)
    local = now.astimezone(ET)
    manual = os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
    nyse = mcal.get_calendar('NYSE')
    schedule = nyse.schedule(start_date=local.date(), end_date=local.date())
    if schedule.empty:
        print(f'NYSE closed on {local.date()}; skip (manual={manual})')
        return
    opening = schedule.iloc[0]['market_open'].to_pydatetime()
    closing = schedule.iloc[0]['market_close'].to_pydatetime()
    window_end = min(opening + __import__('datetime').timedelta(hours=2), closing)
    if not manual and not (opening <= now < window_end):
        print(f'Outside NYSE first 2h; ET={local.isoformat()}, open={opening.astimezone(ET)}, end={window_end.astimezone(ET)}')
        return
    if manual:
        print('Manual diagnostics: V2.2 will use only completed current-session bars if available.')
    monitor_v22.main()


if __name__ == '__main__':
    main()

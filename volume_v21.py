"""Read-only, experimental same-clock-time IEX volume monitor.
Run manually from GitHub Actions; does not send alerts or place orders.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import urllib.parse

from monitor_v2 import SYMBOLS, ET, fetch

MIN_HISTORY = 35
HISTORY_SESSIONS = 50
RATIO_THRESHOLD = 1.5


def time_et(bar):
    return datetime.fromisoformat(bar['t'].replace('Z', '+00:00')).astimezone(ET)


def regular_slot(dt):
    mins = dt.hour * 60 + dt.minute
    return dt.weekday() < 5 and 570 <= mins < 690 and mins % 15 == 0


def load_15m_history(now):
    start = now - timedelta(days=105)
    result = {sym: [] for sym in SYMBOLS}
    page = None
    for _ in range(35):
        params = {
            'symbols': ','.join(SYMBOLS), 'timeframe': '15Min',
            'start': start.isoformat().replace('+00:00', 'Z'),
            'end': now.isoformat().replace('+00:00', 'Z'),
            'feed': os.getenv('ALPACA_FEED', 'iex'),
            'limit': 1000, 'sort': 'asc',
        }
        if page:
            params['page_token'] = page
        payload = fetch(params)
        for sym, bars in payload.get('bars', {}).items():
            if sym in result:
                result[sym].extend(bars)
        page = payload.get('next_page_token')
        if not page:
            return result
    raise RuntimeError('Historical 15-minute data pagination exceeded limit')


def analyze(sym, bars, now):
    now_et = now.astimezone(ET)
    today = now_et.date()
    # A bar starting at 9:30 ET is complete at 9:45 ET.
    completed = now_et - timedelta(minutes=15)
    today_bars = {}
    past = defaultdict(dict)
    for bar in bars:
        dt = time_et(bar)
        if not regular_slot(dt):
            continue
        slot = dt.hour * 60 + dt.minute
        if dt.date() == today:
            if dt <= completed:
                today_bars[slot] = float(bar['v'])
        elif dt.date() < today:
            past[dt.date()][slot] = float(bar['v'])

    # Compare only fully available 15m buckets, starting at 9:30.
    slots = list(range(570, 690, 15))
    consecutive = []
    for slot in slots:
        if slot in today_bars:
            consecutive.append(slot)
        else:
            break
    if not consecutive:
        print(f'{sym}: no completed regular-session 15m IEX bars today; skip')
        return

    cutoff = consecutive[-1]
    needed = [s for s in slots if s <= cutoff]
    samples = []
    for day in sorted(past, reverse=True):
        day_bars = past[day]
        if all(s in day_bars for s in needed):
            samples.append(sum(day_bars[s] for s in needed))
            if len(samples) == HISTORY_SESSIONS:
                break

    current_volume = sum(today_bars[s] for s in needed)
    cutoff_label = f'{(cutoff + 15)//60:02d}:{(cutoff + 15)%60:02d}'
    if len(samples) < MIN_HISTORY:
        print(f'{sym}: {cutoff_label} ET, volume {current_volume:,.0f}; only {len(samples)} comparable historical sessions (need {MIN_HISTORY}); skip signal')
        return

    avg = sum(samples) / len(samples)
    ratio = current_volume / avg if avg > 0 else 0
    status = 'HIGH IEX VOLUME' if ratio >= RATIO_THRESHOLD else 'normal IEX volume'
    print(f'{sym}: through {cutoff_label} ET | today {current_volume:,.0f} | historical {len(samples)}-session same-time mean {avg:,.0f} | {ratio:.2f}x | {status}')


def main():
    now = datetime.now(timezone.utc)
    print('V2.1 same-time IEX volume diagnostic (read-only)')
    print(f'ET: {now.astimezone(ET).isoformat()}')
    print('Historical comparison requires 35+ sessions with complete matching 15-minute buckets.')
    bars = load_15m_history(now)
    for sym in SYMBOLS:
        analyze(sym, bars[sym], now)
    print('Finished. No Telegram notification and no trades.')


if __name__ == '__main__':
    main()

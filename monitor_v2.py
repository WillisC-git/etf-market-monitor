"""Read-only GLD/SLV/IBIT technical monitor using Alpaca IEX data."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SYMBOLS = {'GLD': (385.0, 373.3), 'SLV': (52.8, 50.0), 'IBIT': (47.5, 45.0)}
BASE = 'https://data.alpaca.markets/v2/stocks/bars'
ET = ZoneInfo('America/New_York')
FEED = os.getenv('ALPACA_FEED', 'iex')


def fetch(params):
    key = os.getenv('ALPACA_API_KEY_ID')
    secret = os.getenv('ALPACA_SECRET_KEY')
    if not key or not secret:
        raise RuntimeError('Missing ALPACA_API_KEY_ID or ALPACA_SECRET_KEY')
    url = BASE + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Alpaca HTTP {e.code}; verify data entitlement and API keys') from e


def get_bars(timeframe, start, end):
    result = {s: [] for s in SYMBOLS}
    page = None
    for _ in range(12):
        params = {'symbols': ','.join(SYMBOLS), 'timeframe': timeframe,
                  'start': start.isoformat().replace('+00:00', 'Z'),
                  'end': end.isoformat().replace('+00:00', 'Z'),
                  'feed': FEED, 'limit': 1000, 'sort': 'asc'}
        if page:
            params['page_token'] = page
        data = fetch(params)
        for sym, bars in data.get('bars', {}).items():
            if sym in result:
                result[sym].extend(bars)
        page = data.get('next_page_token')
        if not page:
            return result
    raise RuntimeError('Too many pages; increase pagination limit')


def mean(values):
    return sum(values) / len(values)


def analyze(sym, history, intraday, now):
    # Historical indicators use completed prior-day bars only.
    today_et = now.astimezone(ET).date()
    history = sorted((b for b in history if datetime.fromisoformat(b['t'].replace('Z', '+00:00')).astimezone(ET).date() < today_et), key=lambda b: b['t'])
    if len(history) < 200:
        print(f'{sym}: INSUFFICIENT HISTORY ({len(history)} daily bars; need 200)')
        return False
    closes = [float(b['c']) for b in history]
    volumes = [float(b['v']) for b in history]
    ma50, ma150, ma200 = (mean(closes[-n:]) for n in (50, 150, 200))
    vol50 = mean(volumes[-50:])
    last_completed_close = closes[-1]
    # Intraday price is used only if its bar belongs to the current ET date.
    current = sorted((b for b in intraday if datetime.fromisoformat(b['t'].replace('Z', '+00:00')).astimezone(ET).date() == today_et), key=lambda b: b['t'])
    price = float(current[-1]['c']) if current else last_completed_close
    reference = 'current-session IEX 15m close' if current else 'previous completed IEX daily close'
    up, down = SYMBOLS[sym]
    score = 0
    reasons = []
    for n, ma in ((50, ma50), (150, ma150), (200, ma200)):
        if price > ma:
            score += 10
            reasons.append(f'above MA{n}')
    if ma50 > ma150 > ma200:
        score += 10
        reasons.append('MA50>MA150>MA200')
    if len(closes) >= 205 and ma50 > mean(closes[-55:-5]):
        score += 10
        reasons.append('MA50 rising over 5 sessions')
    if price >= up:
        score += 10
        reasons.append('above upside observation')
    if price < down:
        score -= 10
        reasons.append('below downside observation')
    change_pct = (price / last_completed_close - 1) * 100
    if change_pct >= 3:
        score += 10
        reasons.append('up >=3% vs previous close')
    if change_pct <= -3:
        score -= 10
        reasons.append('down <=-3% vs previous close')
    # Remaining 30 points reserved for validated intraday volume and strength signals.
    score = max(0, min(100, score))
    print(f'\n{sym}: ${price:.2f} ({reference}); vs prior close {change_pct:+.2f}%')
    print(f'  MA50 ${ma50:.2f} | MA150 ${ma150:.2f} | MA200 ${ma200:.2f}')
    print(f'  50-session IEX daily average volume: {vol50:,.0f} shares')
    if current:
        today_volume = sum(float(b['v']) for b in current)
        print(f'  IEX intraday 15m-bar cumulative volume: {today_volume:,.0f} shares; {today_volume/vol50:.1%} of full-day historical average')
        print('  Note: intraday cumulative vs full-day average is NOT a like-for-like volume spike signal.')
    else:
        print('  No current-session IEX 15m bars; volume alert not evaluated.')
    print(f'  Provisional trend score: {score}/100 (30 points reserved; not a complete 100-point model)')
    print(f'  Signals: {", ".join(reasons) if reasons else "none"}')
    print(f'  Watch levels: upside ${up:.2f}; downside ${down:.2f}')
    return True


def main():
    now = datetime.now(timezone.utc)
    et = now.astimezone(ET)
    manual = os.getenv('GITHUB_EVENT_NAME') == 'workflow_dispatch' or '--manual' in sys.argv
    # First two hours of regular session, weekdays; US market holidays not yet checked.
    within_window = et.weekday() < 5 and (9 * 60 + 30) <= (et.hour * 60 + et.minute) < (11 * 60 + 30)
    if not manual and not within_window:
        print(f'Outside monitoring window; ET {et.isoformat()}')
        return
    print(f'Mode: {"manual" if manual else "scheduled"}; ET {et.isoformat()}; feed {FEED}')
    end = now
    daily = get_bars('1Day', now - timedelta(days=420), end)
    intraday = get_bars('15Min', now - timedelta(days=2), end)
    ok = [analyze(sym, daily[sym], intraday[sym], now) for sym in SYMBOLS]
    if not all(ok):
        raise RuntimeError('One or more symbols lack 200 completed daily bars; check IEX data availability')
    print('\nCompleted read-only analysis; no orders placed, no Telegram messages sent.')


if __name__ == '__main__':
    main()

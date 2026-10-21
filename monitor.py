"""GLD/SLV/IBIT read-only Alpaca market monitor. No orders."""
import os
import sys
import json
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SYMBOLS = ['GLD', 'SLV', 'IBIT']
LEVELS = {'GLD': (385.0, 373.3), 'SLV': (52.8, 50.0), 'IBIT': (47.5, 45.0)}
ET = ZoneInfo('America/New_York')
TW = ZoneInfo('Asia/Taipei')
API = 'https://data.alpaca.markets/v2/stocks'

def get(path, params):
    url = API + path + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        'APCA-API-KEY-ID': os.environ['ALPACA_API_KEY_ID'],
        'APCA-API-SECRET-KEY': os.environ['ALPACA_SECRET_KEY'],
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(request, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f'Alpaca HTTP {e.code}; verify account market-data permissions and feed.', file=sys.stderr)
        sys.exit(1)

def notify(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat:
        print('Telegram not configured; alert logged only.')
        return
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    body = urllib.parse.urlencode({'chat_id': chat, 'text': message}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as r:
            print('Telegram status:', r.status)
    except urllib.error.HTTPError as e:
        print(f'Telegram HTTP {e.code} (check bot token/chat ID).', file=sys.stderr)

def main():
    now = datetime.now(timezone.utc)
    et = now.astimezone(ET)
    tw = now.astimezone(TW)
    # Check at US market open, and in the requested Taiwan 22:00-00:00 window.
    opening = et.hour == 9 and 30 <= et.minute < 45
    tw_min = tw.hour * 60 + tw.minute
    in_window = 22 * 60 <= tw_min < 24 * 60
    if et.weekday() >= 5 or not (opening or in_window) or not (9 * 60 + 30 <= et.hour * 60 + et.minute < 16 * 60):
        print('Outside monitoring window. ET:', et.isoformat(), 'TW:', tw.isoformat())
        return
    # Holiday calendar from Alpaca trading API isn't available through market data credentials;
    # absent live bars on holidays will result in no actionable signal.
    print('Check at ET', et.isoformat(), 'TW', tw.isoformat())
    feed = os.environ.get('ALPACA_FEED', 'iex')
    end = now - timedelta(minutes=1)  # allow for delayed/free feed
    start = now - timedelta(days=110)
    history = {}
    page_token = None
    # 110 calendar days normally covers >=50 sessions. Fetch per symbol to avoid global limit ambiguity.
    for symbol in SYMBOLS:
        params = {'symbols': symbol, 'timeframe': '1Day', 'start': start.isoformat().replace('+00:00','Z'),
                  'end': end.isoformat().replace('+00:00','Z'), 'limit': 1000, 'feed': feed}
        bars = []
        while True:
            if page_token: params['page_token'] = page_token
            else: params.pop('page_token', None)
            obj = get('/bars', params)
            bars.extend(obj.get('bars', {}).get(symbol, []))
            page_token = obj.get('next_page_token')
            if not page_token: break
        history[symbol] = bars
        page_token = None
    latest = get('/snapshots', {'symbols': ','.join(SYMBOLS), 'feed': feed})
    signals = []
    for symbol in SYMBOLS:
        snap = latest.get(symbol, {})
        trade = snap.get('latestTrade') or {}
        daily = snap.get('dailyBar') or {}
        prev = snap.get('prevDailyBar') or {}
        price = trade.get('p') or daily.get('c')
        prev_close = prev.get('c')
        volume = daily.get('v')
        bars = history[symbol]
        # Filter out the current trading date, to avoid mixing partial daily volume into average.
        past = [b for b in bars if b.get('t','')[:10] < et.date().isoformat()]
        avg50 = sum(float(b['v']) for b in past[-50:]) / 50 if len(past) >= 50 else None
        print(f'{symbol}: price={price}, prev_close={prev_close}, volume={volume}, '
              f'avg50={round(avg50) if avg50 else "N/A"}, feed={feed}, latestTradeTime={trade.get("t")}')
        if price is None or prev_close is None or volume is None:
            continue
        change = (float(price) / float(prev_close) - 1) * 100
        upper, lower = LEVELS[symbol]
        # Crossing can't be established from a single snapshot; report threshold status, not fresh crossing.
        flags = []
        if float(price) >= upper: flags.append(f'price at/above upper ${upper}')
        if float(price) <= lower: flags.append(f'price at/below lower ${lower}')
        if avg50 is not None and float(volume) > avg50:
            flags.append('intraday volume already exceeds full-day 50-session average')
        if avg50 is not None and abs(change) >= 3 and float(volume) > avg50:
            flags.append('>=3% move with confirmed full-day-average volume')
        if flags:
            signals.append(f'{symbol} ${float(price):.2f} ({change:+.2f}%), volume {volume:,}; ' + '; '.join(flags))
    if opening:
        notify('US market opening check (data may be delayed)\n' + ('\n'.join(signals) if signals else 'No verified threshold signal. See GitHub Actions logs for prices.'))
    elif signals:
        # No persistent state yet: repeated alerts possible; deduplication will be added in next phase.
        notify('ETF monitoring alert (snapshot; not a confirmed fresh crossing)\n' + '\n'.join(signals))
    else:
        print('No verified threshold signal.')

if __name__ == '__main__':
    main()

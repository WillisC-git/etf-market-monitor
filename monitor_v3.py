"""V3.0: NYSE first-two-hours, completed 15m IEX bars, LINE alerts.

Requires monitor_v2.py, monitor_v22.py, volume_v21.py and pandas_market_calendars.
No orders. State is stored in alert_state.json; persist it between GitHub Actions
runs with actions/cache restore/save and a unique per-run cache key.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import request, error

import pandas_market_calendars as mcal
from monitor_v2 import SYMBOLS, ET, get_bars, mean
from volume_v21 import load_15m_history, time_et
from monitor_v22 import completed_today, volume_comparison

STATE_FILE = Path('alert_state.json')


def line_push(message):
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    user = os.environ.get('LINE_USER_ID')
    if not token or not user:
        raise RuntimeError('Missing LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID')
    body = json.dumps({'to': user, 'messages': [{'type': 'text', 'text': message[:4900]}]}).encode()
    req = request.Request('https://api.line.me/v2/bot/message/push', data=body,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    try:
        with request.urlopen(req, timeout=20) as resp:
            print('LINE API HTTP', resp.status)
    except error.HTTPError as exc:
        raise RuntimeError(f'LINE API HTTP {exc.code}: {exc.read(300).decode(errors="replace")}') from exc


def load_state(day):
    try:
        state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        if state.get('date') == day and isinstance(state.get('sent'), list):
            return set(state['sent'])
    except (FileNotFoundError, ValueError, OSError):
        pass
    return set()


def save_state(day, sent):
    temp = STATE_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps({'date': day, 'sent': sorted(sent)}, indent=2) + '\n', encoding='utf-8')
    temp.replace(STATE_FILE)


def analyze(symbol, daily, intraday, now):
    today = now.astimezone(ET).date()
    history = sorted((b for b in daily if time_et(b).date() < today), key=lambda b: b['t'])
    if len(history) < 205:
        raise RuntimeError(f'{symbol}: insufficient daily history ({len(history)}/205)')
    closes = [float(b['c']) for b in history]
    slots, bars = completed_today(intraday, now)
    if not slots:
        print(symbol, 'no completed 15-minute bars yet')
        return []
    price = float(bars[slots[-1]]['c'])
    pct = (price / closes[-1] - 1) * 100
    ma50, ma150, ma200 = (mean(closes[-n:]) for n in (50, 150, 200))
    upper, lower = SYMBOLS[symbol]
    score = sum(10 for ma in (ma50, ma150, ma200) if price > ma)
    score += 10 if ma50 > ma150 > ma200 else 0
    score += 10 if ma50 > mean(closes[-55:-5]) else 0
    score += 10 if price >= upper else 0
    score -= 10 if price < lower else 0
    score += 10 if pct >= 3 else (-10 if pct <= -3 else 0)
    volume, samples = volume_comparison(intraday, slots, now)
    ratio = volume[0] if volume is not None else None
    if ratio is not None and ratio >= 1.5:
        score += 10
    score = max(0, min(100, score))
    cutoff = slots[-1] + 15
    time_label = f'{cutoff // 60:02d}:{cutoff % 60:02d} ET'
    print(f'{symbol} {time_label}: ${price:.2f}, {pct:+.2f}%, score={score}, IEX ratio={ratio}, samples={samples}')
    events = []
    if price >= upper:
        events.append(('ABOVE_UPSIDE_WATCH', f'突破上方觀察價 ${upper:.2f}'))
    if price < lower:
        events.append(('BELOW_DOWNSIDE_WATCH', f'跌破下方觀察價 ${lower:.2f}'))
    if pct >= 3:
        events.append(('DAILY_UP_3_PERCENT', '當日上漲達 3%'))
    if pct <= -3:
        events.append(('DAILY_DOWN_3_PERCENT', '當日下跌達 3%'))
    if ratio is not None and ratio >= 1.5:
        events.append(('HIGH_IEX_VOLUME', f'同時段 IEX 成交量達 {ratio:.2f} 倍'))
    details = (f'{symbol} | {time_label}\n價格 ${price:.2f} | 漲跌 {pct:+.2f}%\n'
               f'MA50 ${ma50:.2f} / MA150 ${ma150:.2f} / MA200 ${ma200:.2f}\n'
               f'同時段 IEX 量比 {f"{ratio:.2f}x" if ratio is not None else "資料不足"}\n'
               f'暫定評分 {score}/100')
    return [(f'{symbol}:{code}', label, details) for code, label in events]


def main():
    now = datetime.now(timezone.utc)
    local = now.astimezone(ET)
    calendar = mcal.get_calendar('NYSE')
    schedule = calendar.schedule(start_date=local.date(), end_date=local.date())
    if schedule.empty:
        print('NYSE closed; no alerts')
        return
    opening = schedule.iloc[0]['market_open'].to_pydatetime()
    closing = schedule.iloc[0]['market_close'].to_pydatetime()
    end = min(opening + timedelta(hours=2), closing)
    if not opening <= now < end:
        print('Outside NYSE first-two-hours window; no alerts')
        return
    day = local.date().isoformat()
    sent = load_state(day)
    print(f'V3.0 | {local.isoformat()} | existing sent keys: {len(sent)}')
    daily = get_bars('1Day', now - timedelta(days=430), now)
    intraday = load_15m_history(now)
    pending = []
    for symbol in SYMBOLS:
        pending.extend(analyze(symbol, daily[symbol], intraday[symbol], now))
    fresh = [(key, label, details) for key, label, details in pending if key not in sent]
    if not fresh:
        print('No new alerts')
        return
    for key, label, details in fresh:
        message = f'📊 ETF Market Monitor V3.0\n⚠️ {label}\n{details}\n\n僅供觀察，非交易建議。'
        line_push(message)
        sent.add(key)
        save_state(day, sent)
        print('Alert sent:', key)


if __name__ == '__main__':
    main()

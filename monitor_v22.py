"""V2.2 read-only ETF monitor: trend + comparable 15m IEX volume + watch levels.
Requires monitor_v2.py and volume_v21.py in the same repository.
No orders, notifications, or persistent deduplication.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from monitor_v2 import SYMBOLS, ET, get_bars, mean
from volume_v21 import load_15m_history, time_et, regular_slot

MIN_HISTORY = 35
VOLUME_THRESHOLD = 1.5


def completed_today(bars, now):
    """Only completed regular-session bars, first two hours (09:30-11:30 ET)."""
    et = now.astimezone(ET)
    cutoff = et - timedelta(minutes=15)
    out = {}
    for bar in bars:
        dt = time_et(bar)
        if dt.date() == et.date() and regular_slot(dt) and dt <= cutoff:
            out[dt.hour * 60 + dt.minute] = bar
    slots = []
    for slot in range(570, 690, 15):
        if slot not in out:
            break
        slots.append(slot)
    return slots, out


def volume_comparison(bars, slots, now):
    if not slots:
        return None, 0
    today = now.astimezone(ET).date()
    historical = {}
    for bar in bars:
        dt = time_et(bar)
        if dt.date() >= today or not regular_slot(dt):
            continue
        historical.setdefault(dt.date(), {})[dt.hour * 60 + dt.minute] = float(bar['v'])
    samples = []
    for day in sorted(historical, reverse=True):
        daybars = historical[day]
        if all(s in daybars for s in slots):
            samples.append(sum(daybars[s] for s in slots))
            if len(samples) == 50:
                break
    if len(samples) < MIN_HISTORY:
        return None, len(samples)
    today_bars = {time_et(b).hour * 60 + time_et(b).minute: b for b in bars if time_et(b).date() == today and regular_slot(time_et(b))}
    total = sum(float(today_bars[s]['v']) for s in slots)
    avg = mean(samples)
    return ((total / avg) if avg > 0 else None, total, avg), len(samples)


def analyze(symbol, daily, intraday, now):
    today = now.astimezone(ET).date()
    daily = sorted((b for b in daily if time_et(b).date() < today), key=lambda b: b['t'])
    if len(daily) < 205:
        print(f'{symbol}: insufficient completed daily history: {len(daily)} (need 205); no signal')
        return False
    closes = [float(b['c']) for b in daily]
    ma50, ma150, ma200 = (mean(closes[-n:]) for n in (50, 150, 200))
    slots, current = completed_today(intraday, now)
    print(f'\n{symbol} | completed 15m bars: {len(slots)}')
    if not slots:
        print('  No completed first-two-hours bars today; skip all intraday alerts')
        return True
    price = float(current[slots[-1]]['c'])
    change = (price / closes[-1] - 1) * 100
    up, down = SYMBOLS[symbol]
    score = 0
    reasons = []
    for n, ma in ((50, ma50), (150, ma150), (200, ma200)):
        if price > ma:
            score += 10
            reasons.append(f'price > MA{n}')
    if ma50 > ma150 > ma200:
        score += 10
        reasons.append('MA50 > MA150 > MA200')
    if ma50 > mean(closes[-55:-5]):
        score += 10
        reasons.append('MA50 rising (5 sessions)')
    if price >= up:
        score += 10
        reasons.append(f'price >= upside ${up:.2f}')
    if price < down:
        score -= 10
        reasons.append(f'price < downside ${down:.2f}')
    if change >= 3:
        score += 10
        reasons.append('change >= +3%')
    elif change <= -3:
        score -= 10
        reasons.append('change <= -3%')

    comparison, n = volume_comparison(intraday, slots, now)
    volume_high = False
    if comparison is None:
        print(f'  Same-time IEX volume: insufficient history ({n}/35 required); no volume alert')
    else:
        ratio, total, avg = comparison
        if ratio is None:
            print('  Same-time IEX volume: historical average zero; no volume alert')
        else:
            volume_high = ratio >= VOLUME_THRESHOLD
            if volume_high:
                score += 10
                reasons.append(f'same-time IEX volume {ratio:.2f}x')
            print(f'  IEX same-time volume: {total:,.0f} / {avg:,.0f} = {ratio:.2f}x (n={n})')
    score = max(0, min(100, score))
    cutoff = slots[-1] + 15
    print(f'  As of {cutoff // 60:02d}:{cutoff % 60:02d} ET | price ${price:.2f} | vs prior IEX close {change:+.2f}%')
    print(f'  MA50 ${ma50:.2f} | MA150 ${ma150:.2f} | MA200 ${ma200:.2f}')
    print(f'  Provisional score: {score}/100 (20 points reserved; not a validated trading signal)')
    print(f'  Factors: {", ".join(reasons) if reasons else "none"}')
    alerts = []
    if price >= up:
        alerts.append('ABOVE_UPSIDE_WATCH')
    if price < down:
        alerts.append('BELOW_DOWNSIDE_WATCH')
    if abs(change) >= 3:
        alerts.append('DAILY_MOVE_3_PERCENT')
    if volume_high:
        alerts.append('HIGH_IEX_VOLUME')
    print(f'  Candidate alerts (diagnostic only): {", ".join(alerts) if alerts else "none"}')
    return True


def main():
    now = datetime.now(timezone.utc)
    et = now.astimezone(ET)
    manual = os.getenv('GITHUB_EVENT_NAME') == 'workflow_dispatch' or '--manual' in sys.argv
    minutes = et.hour * 60 + et.minute
    if not manual and not (et.weekday() < 5 and 570 <= minutes < 705):
        print(f'Outside first-two-hours monitoring window; ET {et.isoformat()}')
        return
    print(f'ETF Monitor V2.2 | {"manual" if manual else "scheduled"} | ET {et.isoformat()}')
    print('IEX-only volume; 15-minute completed bars; read-only; no notifications or orders.')
    daily = get_bars('1Day', now - timedelta(days=430), now)
    intraday = load_15m_history(now)
    results = [analyze(s, daily[s], intraday[s], now) for s in SYMBOLS]
    if not all(results):
        raise RuntimeError('Insufficient daily history for at least one ETF')
    print('\nV2.2 diagnostic completed.')


if __name__ == '__main__':
    main()

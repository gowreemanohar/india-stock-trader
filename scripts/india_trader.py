"""Standalone public-data research helpers. No credentials, project access or file writes."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

from chart_rules import find_setups

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), 'Asia/Kolkata')
FIVE = dt.timedelta(minutes=5)
MAX_BYTES = 8 * 1024 * 1024


def now_ist(value=None):
    if value is None:
        return dt.datetime.now(IST)
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)


def symbols(text):
    result = list(dict.fromkeys(s.strip().upper() for s in text.split(',')))
    if not 1 <= len(result) <= 50:
        raise ValueError('Provide 1 to 50 explicit equity symbols per batch.')
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9&-]{0,30}\.(NS|BO)', s) for s in result):
        raise ValueError('Use verified Indian provider symbols ending in .NS or .BO.')
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirect refused.')


def fetch(symbol, interval):
    query = urllib.parse.urlencode({'interval': interval, 'range': '3mo' if interval == '1d' else '5d', 'includePrePost': 'false'})
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(symbol, safe='') + '?' + query
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 india-stock-trader/1.0'})
    # Explicitly disable environment proxies and redirects; no credentials/cookies are loaded.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Provider response exceeds size limit.')
    return json.loads(raw)


def load_offline(path):
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise ValueError('Offline input exceeds size limit.')
    return json.loads(p.read_text(encoding='utf-8'))


def numeric(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return value > 0 if positive else value >= 0


def parse_chart(doc, symbol, interval):
    chart = doc['chart']
    if chart.get('error') or not chart.get('result'):
        raise ValueError('Provider returned no chart.')
    result = chart['result'][0]
    meta = result['meta']
    if meta.get('symbol', '').upper() != symbol or meta.get('currency') != 'INR':
        raise ValueError('Provider symbol/currency mismatch.')
    if meta.get('instrumentType') != 'EQUITY':
        raise ValueError('Provider instrument is not a cash equity.')
    if meta.get('dataGranularity') != interval:
        raise ValueError('Provider bar interval mismatch.')
    quote = result['indicators']['quote'][0]
    stamps = result.get('timestamp', [])
    if any(len(quote.get(k, [])) != len(stamps) for k in ('open', 'high', 'low', 'close', 'volume')):
        raise ValueError('Mismatched OHLCV arrays.')
    bars = []
    seen = set()
    for i, stamp in enumerate(stamps):
        if not numeric(stamp) or stamp in seen:
            raise ValueError('Invalid or duplicate bar timestamp.')
        seen.add(stamp)
        vals = {k: quote[k][i] for k in ('open', 'high', 'low', 'close', 'volume')}
        if any(not numeric(vals[k], positive=(k != 'volume')) for k in vals):
            continue  # Missing bars remain gaps; ORB rejects incomplete sessions.
        if not vals['low'] <= min(vals['open'], vals['close']) <= max(vals['open'], vals['close']) <= vals['high']:
            raise ValueError('Invalid OHLC ordering.')
        bars.append({'start': dt.datetime.fromtimestamp(stamp, IST), **vals})
    return meta, sorted(bars, key=lambda b: b['start'])


def daily(bars, now, min_price, min_volume, today_complete=False):
    complete = [b for b in bars if b['start'].date() < now.date() or (today_complete and b['start'].date()==now.date())]
    if len({b['start'].date() for b in complete}) != len(complete):
        raise ValueError('Duplicate daily dates.')
    if len(complete) < 30:
        raise ValueError('Need at least 30 completed prior daily bars.')
    last = complete[-1]
    tags, stats = find_setups([b['close'] for b in complete])
    liquid = last['close'] >= min_price and last['volume'] >= min_volume
    return {'bar_date': last['start'].date().isoformat(), 'close_inr': last['close'], 'volume': last['volume'],
            'age_calendar_days': (now.date() - last['start'].date()).days,
            'passes_user_filters': liquid, 'setups': tags if liquid else [], 'indicators': stats,
            'corporate_actions_checked': False}


def orb(bars, now, day, opening, ending, minutes):
    start = dt.datetime.combine(dt.date.fromisoformat(day), dt.time.fromisoformat(opening), IST)
    end = dt.datetime.combine(start.date(), dt.time.fromisoformat(ending), IST)
    if start.second or end.second or start.microsecond or end.microsecond or end <= start or end - start > dt.timedelta(hours=8):
        raise ValueError('Invalid verified session boundaries.')
    if minutes < 5 or minutes % 5 or start + dt.timedelta(minutes=minutes) >= end:
        raise ValueError('Range must be a positive multiple of five minutes within the session.')
    cutoff = min(now, end)
    if cutoff < start + dt.timedelta(minutes=minutes + 5):
        raise ValueError('No completed post-range bar yet.')
    complete = [b for b in bars if start <= b['start'] and b['start'] + FIVE <= cutoff and b['start'] < end]
    expected = [start + FIVE * i for i in range(int((cutoff - start).total_seconds() // 300))]
    if [b['start'] for b in complete] != expected:
        raise ValueError('Missing, off-grid or stale session bars; no ORB judgment.')
    n = minutes // 5
    high = max(b['high'] for b in complete[:n])
    low = min(b['low'] for b in complete[:n])
    hit = next((b for b in complete[n:] if b['close'] > high), None)
    last = complete[-1]
    return {'session_date': day, 'verified_session_open': start.isoformat(), 'verified_session_end': end.isoformat(),
            'opening_range_high_inr': high, 'opening_range_low_inr': low,
            'first_breakout': None if hit is None else {'confirmed_at': (hit['start'] + FIVE).isoformat(), 'close_inr': hit['close']},
            'last_completed_at': (last['start'] + FIVE).isoformat(), 'last_close_inr': last['close'],
            'still_above_range': last['close'] > high, 'complete_bars': len(complete),
            'research_only': True, 'session_verified_by': 'caller; helper has no exchange calendar'}






def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for mode in ('quote', 'daily', 'orb'):
        p = sub.add_parser(mode)
        p.add_argument('--symbols', required=True)
        p.add_argument('--offline', help='Explicit Yahoo chart JSON or symbol-to-chart mapping')
        if mode != 'quote':
            p.add_argument('--now', help='ISO timestamp; no offset means IST')
        if mode == 'daily':
            p.add_argument('--min-price', type=float, default=0)
            p.add_argument('--min-volume', type=float, default=0)
        if mode == 'orb':
            p.add_argument('--session-date', required=True)
            p.add_argument('--session-open', required=True)
            p.add_argument('--session-end', required=True)
            p.add_argument('--or-minutes', type=int, default=15)
    args = parser.parse_args(argv)
    try:
        requested = symbols(args.symbols)
        now = now_ist(getattr(args, 'now', None))
        offline = load_offline(args.offline) if args.offline else None
        interval = '5m' if args.command == 'orb' else '1d'
        if args.command == 'daily' and (not numeric(args.min_price) or not numeric(args.min_volume)):
            raise ValueError('Liquidity filters must be finite and nonnegative.')
        rows, failures = [], []
        for index, symbol in enumerate(requested):
            try:
                if offline is None:
                    if index:
                        time.sleep(0.4)
                    doc = fetch(symbol, interval)
                else:
                    doc = offline if 'chart' in offline else offline[symbol]
                meta, bars = parse_chart(doc, symbol, interval)
                if args.command == 'daily':
                    data = daily(bars, now, args.min_price, args.min_volume)
                elif args.command == 'orb':
                    data = orb(bars, now, args.session_date, args.session_open, args.session_end, args.or_minutes)
                else:
                    price, stamp = meta.get('regularMarketPrice'), meta.get('regularMarketTime')
                    if not numeric(price, True) or not numeric(stamp):
                        raise ValueError('Missing quote price or timestamp.')
                    quoted = dt.datetime.fromtimestamp(stamp, IST)
                    if quoted > now + dt.timedelta(minutes=1):
                        raise ValueError('Quote timestamp is in the future.')
                    data = {'price_inr': price, 'quoted_at': quoted.isoformat(), 'age_seconds': max(0, int((now - quoted).total_seconds())),
                            'real_time_verified': False}
                rows.append({'symbol': symbol, 'exchange': 'NSE' if symbol.endswith('.NS') else 'BSE', **data})
            except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
                failures.append({'symbol': symbol, 'error': str(error)})
        print(json.dumps({'mode': args.command, 'as_of_ist': now.isoformat(), 'retrieved_at_ist': now_ist().isoformat(),
                          'source': 'explicit offline Yahoo JSON' if offline is not None else 'Yahoo Finance unofficial chart endpoint',
                          'currency': 'INR', 'requested': len(requested), 'succeeded': len(rows), 'failed': len(failures),
                          'partial': bool(failures), 'rows': rows, 'failures': failures}, indent=2, allow_nan=False))
        return 2 if failures else 0
    except (ValueError, OSError, TypeError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

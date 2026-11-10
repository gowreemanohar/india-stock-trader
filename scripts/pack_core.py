"""Shared validation, explicit file I/O, session manifests and public data access."""
import datetime as dt
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import hashlib
import json
import gzip
from pathlib import Path
import urllib.parse
import urllib.request

from india_trader import IST, NoRedirect, now_ist, parse_chart, symbols

LIMIT = 32 * 1024 * 1024
HOSTS = {'query1.finance.yahoo.com', 'query2.finance.yahoo.com', 'nsearchives.nseindia.com',
         'archives.nseindia.com', 'www.nseindia.com', 'www.bseindia.com', 'feeds.finance.yahoo.com'}


def number(value, minimum=0, positive=False):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a number.')
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError('Invalid number.') from exc
    if not result.is_finite() or result < minimum or (positive and result == 0):
        raise ValueError('Number must be finite and within permitted bounds.')
    return result


def integer(value, minimum=0, maximum=1000000):
    n = number(value, minimum)
    if n != n.to_integral_value() or n > maximum:
        raise ValueError('Expected a bounded integer.')
    return int(n)


def symbol(value):
    result = symbols(value)
    if len(result) != 1:
        raise ValueError('One symbol required.')
    return result[0]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_text(path):
    p = Path(path)
    if not p.is_file() or p.stat().st_size > LIMIT:
        raise ValueError('Input must be a regular file at most 32 MiB.')
    if p.suffix.lower() == '.gz':
        with gzip.open(p,'rb') as src:
            data=src.read(LIMIT+1)
        if len(data)>LIMIT:
            raise ValueError('Decompressed input exceeds 32 MiB.')
        return data.decode('utf-8-sig')
    return p.read_text(encoding='utf-8-sig')


def read_json(path):
    return json.loads(read_text(path), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number.')))


def write_json(path, value, replace=False):
    """Only explicitly requested paths; refuse overwrites except explicit state updates."""
    p = Path(path)
    if p.is_symlink():
        raise ValueError('Refusing a symbolic-link output.')
    payload = json.dumps(value, indent=2, allow_nan=False) + '\n'
    with p.open('w' if replace else 'x', encoding='utf-8') as out:
        out.write(payload)


def public_get(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Only allowlisted public HTTPS data hosts are permitted.')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 india-stock-trader/2.0'})
    with opener.open(req, timeout=20) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('Public response exceeds 32 MiB limit.')
    return data.decode('utf-8-sig')


def chart(sym, interval='5m', offline=None, history=False):
    sym = symbol(sym)
    if interval not in ('1m', '5m', '1d'):
        raise ValueError('Unsupported interval.')
    if offline:
        doc = read_json(offline)
        doc = doc if 'chart' in doc else doc[sym]
    else:
        rng = '60d' if history and interval == '5m' else ('5d' if interval != '1d' else '3mo')
        query = urllib.parse.urlencode({'interval': interval, 'range': rng, 'includePrePost': 'false', 'events': 'splits,div'})
        doc = json.loads(public_get('https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(sym, safe='') + '?' + query))
    meta, bars = parse_chart(doc, sym, interval)
    events = doc['chart']['result'][0].get('events', {})
    return meta, bars, events, fingerprint(doc)


def clock(day, value):
    t = dt.time.fromisoformat(value)
    if t.second or t.microsecond or t.tzinfo:
        raise ValueError('Session clocks must be HH:MM IST.')
    return dt.datetime.combine(dt.date.fromisoformat(day), t, IST)


class Calendar:
    """Exact per-security sessions. An absent date is unknown, never a guessed holiday."""
    def __init__(self, doc, sym):
        self.doc = doc
        self.symbol = symbol(sym)
        if doc.get('symbol') != self.symbol or doc.get('timezone') != 'Asia/Kolkata':
            raise ValueError('Calendar must match the symbol and Asia/Kolkata timezone.')
        if not doc.get('source_url') or not doc.get('verified_at'):
            raise ValueError('Calendar needs source_url and verified_at provenance.')
        now_ist(doc['verified_at'])
        if not isinstance(doc.get('sessions'), dict) or not doc['sessions']:
            raise ValueError('Calendar needs explicit dated sessions.')
        self.sessions = {}
        for day, spec in doc['sessions'].items():
            dt.date.fromisoformat(day)
            if spec.get('closed') is True:
                self.sessions[day] = None
                continue
            start, end = clock(day, spec['open']), clock(day, spec['end'])
            if not dt.timedelta(minutes=10) <= end - start <= dt.timedelta(hours=8):
                raise ValueError('Invalid continuous-trading session length.')
            tick = number(spec['tick_size'], positive=True)
            self.sessions[day] = {'start': start, 'end': end, 'tick': tick}

    def get(self, day):
        if day not in self.sessions:
            raise ValueError('Unverified session date: ' + day)
        if self.sessions[day] is None:
            raise ValueError('Exchange closed on ' + day)
        return self.sessions[day]

    def status(self, now):
        day = now.date().isoformat()
        if day not in self.sessions:
            return {'status': 'unknown', 'date': day}
        spec = self.sessions[day]
        if spec is None:
            return {'status': 'closed', 'date': day}
        state = 'not_open' if now < spec['start'] else ('open' if now < spec['end'] else 'closed')
        return {'status': state, 'date': day, 'open': spec['start'].isoformat(), 'end': spec['end'].isoformat()}


def session_bars(bars, spec, now, interval=5, require_full=False):
    start, end = spec['start'], spec['end']
    step = dt.timedelta(minutes=interval)
    if (end - start).total_seconds() % step.total_seconds():
        raise ValueError('Session duration is not aligned to the bar interval.')
    cutoff = end if require_full else min(now, end)
    if require_full and end > now:
        raise ValueError('Full session is not complete as of the clock.')
    count = max(0, int((cutoff - start) // step))
    expected = [start + i * step for i in range(count)]
    rows = [b for b in bars if start <= b['start'] and b['start'] + step <= cutoff]
    if [b['start'] for b in rows] != expected:
        raise ValueError('Missing, duplicate, off-grid or stale bars in verified session.')
    return rows


def tick_price(value, tick, up=False):
    value, tick = number(value, positive=True), number(tick, positive=True)
    return (value / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick


def validate_plan(plan):
    if plan.get('schema') != 'india-plan-v2' or plan.get('currency') != 'INR' or plan.get('side') != 'buy':
        raise ValueError('Expected a long-only INR india-plan-v2 document.')
    symbol(plan['symbol'])
    entry, stop, target, tick = [number(plan[k], positive=True) for k in ('entry', 'stop', 'target', 'tick_size')]
    if not stop < entry < target:
        raise ValueError('Plan requires stop < entry < target.')
    if any(v % tick for v in (entry, stop, target)):
        raise ValueError('Plan prices are not on the specified tick grid.')
    at, flat, start, end = [now_ist(plan[k]) for k in ('entry_at', 'flat_by', 'session_open', 'session_end')]
    if not start < at < flat <= end or len({x.date() for x in (at, flat, start, end)}) != 1:
        raise ValueError('Plan times must be within one verified session.')
    if number(plan.get('cost_per_share',0)) or number(plan.get('slippage_bps',0)):
        raise ValueError('Original-pack parity: nonzero fee/slippage extensions are not supported.')
    return entry, stop, target

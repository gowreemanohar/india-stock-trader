"""Official equity universes, exchange feeds, filed financials and disclosure tracking."""
import csv
import datetime as dt
from decimal import Decimal
import email.utils
import html
import io
import re
import urllib.parse
import xml.etree.ElementTree as ET

from pack_core import IST, number, symbol, fingerprint, public_get, now_ist

NSE_UNIVERSE = 'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv'
FEEDS = {
    'nse-announcements': 'https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml',
    'nse-results': 'https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml',
    'nse-integrated-financials': 'https://nsearchives.nseindia.com/content/RSS/Integrated_Filing_Financials.xml',
    'nse-insiders': 'https://nsearchives.nseindia.com/content/RSS/InsiderTrading.xml',
    'nse-shareholding': 'https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml',
    'nse-encumbrance': 'https://nsearchives.nseindia.com/content/RSS/Sast_ReasonForEncumbrance.xml',
    'nse-board': 'https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml',
    'nse-actions': 'https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml',
    'bse-announcements': 'https://www.bseindia.com/data/xml/announcements.xml',
    'bse-insiders': 'https://www.bseindia.com/Data/XML/InsiderTradingFeed.aspx',
}
TAGS = {'earnings': ('financial result', 'earnings', 'quarter', 'profit'),
        'capital': ('dividend', 'bonus', 'split', 'rights issue', 'buyback', 'allotment'),
        'people': ('resignation', 'appointment', 'director'), 'deal': ('acquisition', 'merger', 'order win'),
        'regulatory': ('sebi', 'penalty', 'regulation', 'compliance'), 'risk': ('default', 'fraud', 'insolvency', 'cyber'),
        'halt': ('suspension', 'trading halt'), 'disclosure': ('insider', 'shareholding', 'encumbrance', 'promoter')}


def universe(text, exchange='NSE'):
    reader = csv.DictReader(io.StringIO(text))
    rows, skipped = [], 0
    for raw in reader:
        row = {k.strip().upper(): (v or '').strip() for k, v in raw.items() if k}
        if exchange == 'NSE':
            if row.get('SERIES') != 'EQ' or row.get('MARKET LOT') != '1':
                skipped += 1
                continue
            sym = symbol(row['SYMBOL'] + '.NS')
            name, isin = row['NAME OF COMPANY'], row['ISIN NUMBER']
        else:
            # Explicit verified provider mapping avoids guessing from scrip codes.
            if row.get('STATUS', 'ACTIVE').upper() != 'ACTIVE' or row.get('INSTRUMENT TYPE') != 'EQUITY':
                skipped += 1
                continue
            sym = symbol(row['YAHOO SYMBOL'])
            if not sym.endswith('.BO'):
                raise ValueError('BSE import requires verified .BO symbols.')
            name, isin = row['NAME'], row['ISIN']
        if not name or not re.fullmatch(r'IN[A-Z0-9]{10}', isin):
            raise ValueError('Missing company name or malformed Indian ISIN.')
        rows.append({'symbol': sym, 'name': name, 'isin': isin, 'exchange': exchange})
    if not rows:
        raise ValueError('No supported equity rows; check CSV schema and exchange.')
    if len({row['symbol'] for row in rows}) != len(rows):
        raise ValueError('Duplicate symbols in security master.')
    return {'schema': 'india-universe-v2', 'exchange': exchange, 'count': len(rows), 'skipped': skipped,
            'rows': rows, 'retrieved_at': now_ist().isoformat(), 'note': 'Current constituents, not a point-in-time historical universe.'}


def clean_text(text):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', text or ''))).strip()


def feed_time(value):
    if not value:
        return None
    try:
        result = email.utils.parsedate_to_datetime(value)
        return (result.replace(tzinfo=IST) if result.tzinfo is None else result.astimezone(IST)).isoformat()
    except (ValueError, TypeError):
        pass
    for pattern in ('%d-%b-%Y %H:%M:%S', '%d-%m-%Y %H:%M:%S', '%d %b %Y %H:%M:%S'):
        try:
            return dt.datetime.strptime(value, pattern).replace(tzinfo=IST).isoformat()
        except ValueError:
            pass
    return None


def parse_feed(text, source, query=None, since=None, seen=None):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('XML document type/entity declarations are not accepted.')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('Malformed RSS XML.') from exc
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('Expected an RSS channel, not an HTML error or login page.')
    rows, state, skipped = [], dict(seen or {}), 0
    tokens = [t.strip().casefold() for t in (query or '').split(',') if t.strip()]
    after = now_ist(since) if since else None
    for item in root.findall('./channel/item'):
        title = clean_text(item.findtext('title'))
        description = clean_text(item.findtext('description'))
        link = (item.findtext('link') or '').strip()
        parsed = urllib.parse.urlsplit(link)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            link = None
        text_match = (title + ' ' + description + ' ' + (item.findtext('scripcode') or '')).casefold()
        if tokens and not any(re.search(r'(?<!\w)' + re.escape(t) + r'(?!\w)', text_match) for t in tokens):
            skipped += 1
            continue
        raw_time = item.findtext('pubDate')
        published = feed_time(raw_time)
        if after and published and now_ist(published) < after:
            skipped += 1
            continue
        identity = fingerprint({'title': title, 'description': description, 'url': link, 'published': raw_time})
        new = identity not in state
        state[identity] = published or now_ist().isoformat()
        rows.append({'id': identity, 'title': title, 'description': description, 'source_url': link,
                     'published_at_ist': published, 'published_raw': raw_time, 'new': new,
                     'tags': [tag for tag, terms in TAGS.items() if any(t in text_match for t in terms)],
                     'document_read': False})
    # Prune explicit feed state; unknown publication dates are timestamped at first observation.
    cutoff = now_ist() - dt.timedelta(days=90)
    state = {k: v for k, v in state.items() if now_ist(v) >= cutoff}
    return {'schema': 'india-news-v2', 'source': source, 'feed_built_at_raw': root.findtext('./channel/lastBuildDate'),
            'fetched_at': now_ist().isoformat(), 'items': rows, 'matched': len(rows), 'skipped': skipped,
            'state': state, 'coverage': 'Recent feed window only; an empty feed does not prove there were no filings.',
            'warning': 'Read the linked primary document before treating a headline as an established event.'}


def financial_analysis(doc):
    sym = symbol(doc['symbol'])
    scope = doc['scope']
    if scope not in ('consolidated', 'standalone'):
        raise ValueError('Financial scope must be consolidated or standalone.')
    units = {'INR': Decimal(1), 'lakh': Decimal(100000), 'crore': Decimal(10000000), 'million_inr': Decimal(1000000)}
    # Original analyst behavior: latest filed revision wins; derive Q4 from FY minus Q1-Q3.
    latest={}
    for raw in doc['periods']:
        if raw.get('scope',scope)!=scope: raise ValueError('Mixed financial scope.')
        key=(raw['start'],raw['end'])
        if key not in latest or now_ist(raw['filed_at'])>now_ist(latest[key]['filed_at']): latest[key]=dict(raw)
    quarters=[]; annual=[]
    for raw in latest.values():
        days=(dt.date.fromisoformat(raw['end'])-dt.date.fromisoformat(raw['start'])).days+1
        if 70<=days<=100: quarters.append(raw)
        elif 350<=days<=380: annual.append(raw)
        else: raise ValueError('Use discrete quarters or full years, not unmarked year-to-date totals.')
    for year in annual:
        if any(q['end']==year['end'] for q in quarters): continue
        inside=sorted((q for q in quarters if q['start']>=year['start'] and q['end']<year['end']),key=lambda q:q['start'])
        if len(inside)!=3 or inside[0]['start']!=year['start']: continue
        if any(dt.date.fromisoformat(inside[i]['end'])+dt.timedelta(days=1)!=dt.date.fromisoformat(inside[i+1]['start']) for i in range(2)): continue
        start=dt.date.fromisoformat(inside[-1]['end'])+dt.timedelta(days=1)
        if not 70<=(dt.date.fromisoformat(year['end'])-start).days+1<=100: continue
        derived=dict(year,start=start.isoformat(),unit='INR',derived=True,
                     source_urls=[year['source_url']]+[q['source_url'] for q in inside],
                     filed_at=max([year['filed_at']]+[q['filed_at'] for q in inside],key=now_ist))
        for key in ('revenue','operating_profit','pat','operating_cash_flow','exceptional_items','eps'):
            if year.get(key) is not None and all(q.get(key) is not None for q in inside):
                value=Decimal(str(year[key]))*(1 if key=='eps' else units[year['unit']])
                derived[key]=str(value-sum(Decimal(str(q[key]))*(1 if key=='eps' else units[q['unit']]) for q in inside))
            else: derived.pop(key,None)
        for key in ('debt','cash'):
            if year.get(key) is not None: derived[key]=str(Decimal(str(year[key]))*units[year['unit']])
        quarters.append(derived)
    periods = []
    identity = set()
    for raw in quarters:
        end = dt.date.fromisoformat(raw['end'])
        start = dt.date.fromisoformat(raw['start'])
        duration = (end-start).days+1
        if not 70 <= duration <= 100:
            raise ValueError('Use discrete quarters (70-100 days), not annual or year-to-date totals.')
        if raw.get('scope', scope) != scope or end in identity:
            raise ValueError('Mixed financial scope or duplicate/restated period: select a consistent version.')
        identity.add(end)
        factor = units[raw['unit']]
        filed = now_ist(raw['filed_at'])
        if filed.date() < end or filed > now_ist():
            raise ValueError('Invalid filing timestamp.')
        source = raw['source_url']
        if urllib.parse.urlsplit(source).scheme != 'https':
            raise ValueError('Each financial period needs a primary HTTPS source URL.')
        metrics = {}
        for key in ('revenue', 'operating_profit', 'pat', 'operating_cash_flow', 'debt', 'cash', 'exceptional_items'):
            if raw.get(key) is not None:
                # Profit/cash flow may be negative; finite validation still applies.
                metrics[key] = number(raw[key], minimum=Decimal('-1e30')) * factor
        if raw.get('eps') is not None:
            metrics['eps'] = number(raw['eps'], minimum=Decimal('-1e30'))  # EPS is always INR/share.
        if 'revenue' not in metrics or metrics['revenue'] < 0:
            raise ValueError('Nonnegative revenue is required.')
        periods.append({'start': start, 'end': end, 'filed_at': filed, 'source_url': source, 'metrics': metrics,
                        'derived':raw.get('derived',False),'source_urls':raw.get('source_urls',[source])})
    periods.sort(key=lambda p: p['end'])
    if not periods:
        raise ValueError('No quarterly financial periods.')
    rows = []
    for p in periods:
        prior = next((old for old in periods if old['end'].year == p['end'].year-1 and old['end'].month == p['end'].month
                      and abs(old['end'].day-p['end'].day) <= 3 and abs((old['end']-old['start']).days-(p['end']-p['start']).days) <= 3), None)
        metrics = p['metrics']
        yoy = {}
        if prior:
            for key, value in metrics.items():
                prev = prior['metrics'].get(key)
                yoy[key] = str((value/prev-1)*100) if prev is not None and prev > 0 else None
        revenue = metrics['revenue']
        rows.append({'start': p['start'].isoformat(), 'end': p['end'].isoformat(), 'filed_at': p['filed_at'].isoformat(),
                     'source_url': p['source_url'], 'source_urls':p['source_urls'],'derived_q4':p['derived'],
                     'metrics_inr_except_eps': {k: str(v) for k, v in metrics.items()},
                     'yoy_percent': yoy, 'operating_margin_percent': str(metrics['operating_profit']/revenue*100) if revenue and 'operating_profit' in metrics else None,
                     'pat_margin_percent': str(metrics['pat']/revenue*100) if revenue and 'pat' in metrics else None,
                     'flags': (['PAT exceeds operating profit; inspect non-operating/exceptional items.'] if 'pat' in metrics and 'operating_profit' in metrics and metrics['pat'] > metrics['operating_profit'] else [])})
    return {'schema': 'india-financials-v2', 'symbol': sym, 'scope': scope, 'periods': rows,
            'source_verification': 'Numeric analysis of explicitly transcribed filed data; document extraction must be verified by the caller.',
            'note': 'YoY percentage omitted when prior value is zero/negative; EPS never multiplied by lakh/crore units.'}


def disclosures(doc, seen=None):
    state, rows = dict(seen or {}), []
    for raw in doc['records']:
        sym = symbol(raw['symbol'])
        category = raw['category']
        if category not in ('insider', 'promoter', 'shareholding', 'pledge', 'bulk_deal', 'block_deal'):
            raise ValueError('Unsupported Indian disclosure category.')
        filed = now_ist(raw['filed_at'])
        event = dt.date.fromisoformat(raw['event_date'])
        if event > filed.date() or filed > now_ist():
            raise ValueError('Disclosure event/filing dates are inconsistent.')
        if urllib.parse.urlsplit(raw['source_url']).scheme != 'https':
            raise ValueError('Disclosure requires a primary HTTPS source URL.')
        identity = fingerprint(raw)
        row = dict(raw, symbol=sym, id=identity, new=identity not in state,
                   reporting_delay_days=(filed.date()-event).days)
        if not raw.get('person_or_entity'):
            raise ValueError('Disclosure needs person_or_entity; do not infer the owner.')
        for key in ('quantity', 'value_inr', 'holding_percent', 'pledged_percent'):
            if raw.get(key) is not None:
                val = number(raw[key])
                if key.endswith('percent') and val > 100:
                    raise ValueError('Percentage exceeds 100.')
                row[key] = str(val)
        state[identity] = filed.isoformat()
        rows.append(row)
    return {'schema': 'india-disclosures-v2', 'records': rows, 'state': state,
            'note': 'Disclosed values and dates only. These are not US congressional reports or contemporaneous trading signals.'}

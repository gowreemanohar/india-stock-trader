"""Full standalone Indian cash-equity research and paper-trading pack (standard library)."""
import argparse
import csv
import datetime as dt
import io
import json
from pathlib import Path
import sys
import time
import urllib.parse

import india_trader as legacy
from pack_core import (Calendar, chart, read_json, read_text, write_json, now_ist, symbol,
                       number, integer, public_get, fingerprint)
from research import FEEDS, NSE_UNIVERSE, universe, parse_feed, financial_analysis, disclosures
from simulation import history_sessions, backtest, monte_carlo
from trading import (entry_check, exit_plan, budget, allocate, risk_check,
                     alerts_from_plan, evaluate_alerts)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest='command', required=True)
    def command(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument('--output', help='Write new JSON file at explicit path; existing files are not overwritten')
        return p
    p = command('universe', 'Fetch NSE EQ equities or import verified NSE/BSE CSV')
    p.add_argument('--exchange', choices=['NSE','BSE'], default='NSE')
    p.add_argument('--input')
    p = command('calendar-build', 'Validate explicit date/open/end/tick_size CSV into a session manifest')
    for key in ('symbol','input','source-url','verified-at'):
        p.add_argument('--'+key, required=True)
    for name in ('daily','quote'):
        p = command(name, 'Bounded public-data scan/quote with explicit timestamps')
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument('--symbols')
        group.add_argument('--universe')
        p.add_argument('--limit', type=int, default=50)
        p.add_argument('--offset', type=int, default=0)
        p.add_argument('--offline')
        p.add_argument('--now')
        if name == 'daily':
            p.add_argument('--min-price', type=float, default=0)
            p.add_argument('--min-volume', type=float, default=0)
            p.add_argument('--calendar', help='Verified manifest (one symbol), or symbol-to-manifest mapping, to include a completed current session')
    p = command('fetch', 'Download bounded Yahoo JSON for reproducible offline research')
    p.add_argument('--symbol', required=True)
    p.add_argument('--interval', choices=['1d','5m','1m'], default='5m')
    p.add_argument('--history', action='store_true')
    p = command('entry', 'ORB or level confirmation on completed bars; optional bounded foreground watch')
    p.add_argument('--symbol', required=True)
    p.add_argument('--calendar', required=True)
    p.add_argument('--date')
    p.add_argument('--offline')
    p.add_argument('--now')
    p.add_argument('--interval', type=int, choices=[1,5], default=5)
    p.add_argument('--or-minutes', type=int, default=15)
    p.add_argument('--level')
    p.add_argument('--min-volume-x', type=float, default=0)
    p.add_argument('--no-entries-before')
    p.add_argument('--no-entries-after')
    p.add_argument('--watch-seconds', type=int, default=0)
    p.add_argument('--poll-seconds', type=int, default=60)
    p = command('exit', 'Create a tick-rounded INR exit plan from a confirmed entry')
    p.add_argument('--entry-json', required=True)
    p.add_argument('--stop', default='or-mid')
    p.add_argument('--target', default='2R')
    p.add_argument('--flat-by', required=True)
    p.add_argument('--offline', help='Chart needed only for ATR stops')
    p = command('budget', 'Size an INR paper ticket using limits and explicit account snapshot')
    for key in ('plan','limits','account'):
        p.add_argument('--'+key, required=True)
    p = command('allocate', 'Whole-share weighted allocation without leverage')
    p.add_argument('--input', required=True)
    p = command('risk', 'Recompute portfolio/day/quote/time/tick risk checks')
    for key in ('ticket','limits','account','quote','calendar'):
        p.add_argument('--'+key, required=True)
    p.add_argument('--now')
    p = command('paper', 'Read-only ticket preview and simulation log, as in the installed original')
    p.add_argument('action', choices=['show','log'])
    for key in ('ticket','ledger'):
        p.add_argument('--'+key)
    p = command('alerts', 'Create/list/reset/check rules with explicit state; no implicit monitoring')
    p.add_argument('action', choices=['create','add','list','reset','check','clock'])
    for key in ('plan','rules','quotes','calendar','symbol','state','reset-id','now'):
        p.add_argument('--'+key)
    p.add_argument('--max-age', type=int, default=300)
    p.add_argument('--rule', help='Explicit single-rule JSON to add without changing existing rule IDs')
    for name in ('backtest','timemachine'):
        p = command(name, 'Original historical ORB replay / empirical Monte Carlo')
        p.add_argument('--calendar', required=True)
        p.add_argument('--offline')
        p.add_argument('--now')
        p.add_argument('--strategy', required=(name != 'timemachine'))
        if name == 'timemachine':
            p.add_argument('--plan', required=True)
            p.add_argument('--replays', type=int, default=10000)
            p.add_argument('--window', type=int, default=2)
        else:
            p.add_argument('--symbol', required=True)
            p.add_argument('--before', help='Exclusive session date; defaults to local as-of date')
        p.add_argument('--seed', type=int, default=19)
    p = command('chart', 'Render Monte Carlo price bands as a compact text chart')
    p.add_argument('--input', required=True)
    p = command('news', 'Fetch/parse official recent exchange feeds and optional deduplication state')
    p.add_argument('--feed', choices=list(FEEDS), default='nse-announcements')
    p.add_argument('--offline')
    p.add_argument('--query', help='Comma-separated company names, symbols or BSE codes; explicit matching')
    p.add_argument('--since')
    p.add_argument('--state')
    p.add_argument('--new-only', action='store_true')
    for name in ('analyst','disclosures'):
        p = command(name, 'Analyze explicitly sourced Indian filed financial/disclosure data')
        p.add_argument('--input', required=True)
        if name == 'disclosures':
            p.add_argument('--state')
    return root


def state_read(path):
    return read_json(path) if path and Path(path).exists() else {}


def needed(args, *keys):
    for key in keys:
        if not getattr(args, key, None):
            raise ValueError('--' + key.replace('_','-') + ' is required for this action.')


def run(args):
    mode = args.command
    now = now_ist(getattr(args, 'now', None))
    if mode == 'universe':
        if args.exchange == 'BSE' and not args.input:
            raise ValueError('BSE universe needs an explicit verified security-master CSV; no guessed mappings.')
        result = universe(read_text(args.input) if args.input else public_get(NSE_UNIVERSE), args.exchange)
        result['source'] = args.input or NSE_UNIVERSE
        return result
    if mode == 'calendar-build':
        sessions = {}
        for row in csv.DictReader(io.StringIO(read_text(args.input))):
            day = row['date']
            if day in sessions:
                raise ValueError('Duplicate calendar date.')
            sessions[day] = {'closed': True} if row.get('closed','').lower() == 'true' else {k: row[k] for k in ('open','end','tick_size')}
        result = {'symbol': symbol(args.symbol), 'timezone': 'Asia/Kolkata', 'source_url': args.source_url,
                  'verified_at': args.verified_at, 'sessions': sessions}
        Calendar(result, args.symbol)
        return result
    if mode in ('daily','quote'):
        limit, offset = integer(args.limit,1,50), integer(args.offset,0,100000)
        all_syms = legacy.symbols(args.symbols) if args.symbols else [row['symbol'] for row in read_json(args.universe)['rows']]
        chosen = all_syms[offset:offset+limit]
        rows, errors = [], []
        for i, sym in enumerate(chosen):
            try:
                if i and not args.offline:
                    time.sleep(.4)
                meta, bars, events, digest = chart(sym,'1d',args.offline)
                if mode == 'daily':
                    today_complete=False
                    if args.calendar:
                        manifests=read_json(args.calendar)
                        manifest=manifests if manifests.get('symbol')==sym else manifests[sym]
                        cal=Calendar(manifest,sym)
                        spec=cal.get(now.date().isoformat())
                        today_complete=now>=spec['end']
                    result = legacy.daily(bars, now, float(number(args.min_price)), float(number(args.min_volume)),today_complete)
                    result['provider_corporate_events'] = events
                else:
                    price = number(meta['regularMarketPrice'], positive=True)
                    at = dt.datetime.fromtimestamp(float(number(meta['regularMarketTime'])), legacy.IST)
                    age = (now-at).total_seconds()
                    if age < 0:
                        raise ValueError('Quote is from after the as-of clock.')
                    result = {'price': str(price), 'quoted_at': at.isoformat(), 'age_seconds': int(age), 'real_time_verified': False}
                rows.append(dict(result,symbol=sym,currency='INR',data_fingerprint=digest))
            except (ValueError,KeyError,TypeError,IndexError,OSError) as exc:
                errors.append({'symbol': sym,'error': str(exc)})
        return {'mode': mode,'as_of': now.isoformat(),'source': 'Yahoo Finance (unofficial) or explicit offline Yahoo JSON',
                'universe_count': len(all_syms),'batch_offset': offset,'requested': len(chosen),'succeeded': len(rows),
                'failed': len(errors),'partial': bool(errors) or len(chosen)<len(all_syms),'rows': rows,'errors': errors}
    if mode == 'fetch':
        sym = symbol(args.symbol)
        rng = '60d' if args.history and args.interval == '5m' else ('3mo' if args.interval == '1d' else '5d')
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(sym,safe='') + '?' + urllib.parse.urlencode(
            {'interval':args.interval,'range':rng,'events':'splits,div','includePrePost':'false'})
        result = json.loads(public_get(url))
        legacy.parse_chart(result,sym,args.interval)
        return result
    if mode == 'entry':
        cal = Calendar(read_json(args.calendar),args.symbol)
        watch = integer(args.watch_seconds,0,3600)
        poll = integer(args.poll_seconds,15,60)
        if watch and (args.now or args.offline or args.date):
            raise ValueError('Foreground watching requires current public data, no historical clock/date/offline file.')
        deadline = time.monotonic()+watch
        while True:
            _, bars, _, digest = chart(args.symbol, str(args.interval)+'m',args.offline)
            result = entry_check(args.symbol,bars,cal,now,args.date,args.interval,args.or_minutes,args.level,args.min_volume_x,
                                 args.no_entries_before,args.no_entries_after)
            result['data_fingerprint'] = digest
            if not watch or result['status'] in ('triggered','triggered_earlier','expired') or time.monotonic() >= deadline:
                return result
            print(json.dumps(result),file=sys.stderr,flush=True)
            time.sleep(min(poll,max(0,deadline-time.monotonic())))
            now = now_ist()
    if mode == 'exit':
        entry = read_json(args.entry_json)
        bars = chart(entry['symbol'], str(entry['interval_minutes'])+'m',args.offline)[1] if args.stop.startswith('atr:') else None
        return exit_plan(entry,args.stop,args.target,args.flat_by,bars=bars)
    if mode == 'budget':
        return budget(read_json(args.plan),read_json(args.limits),read_json(args.account))
    if mode == 'allocate':
        doc = read_json(args.input)
        return allocate(doc['weights'],doc['prices'],doc['cash'],doc['position_cap'],doc.get('cash_buffer',0))
    if mode == 'risk':
        ticket = read_json(args.ticket)
        return risk_check(ticket,read_json(args.limits),read_json(args.account),read_json(args.quote),
                          Calendar(read_json(args.calendar),ticket['plan']['symbol']),now)
    if mode == 'paper':
        if args.action == 'show':
            needed(args,'ticket')
            ticket = read_json(args.ticket)
            return {'ticket':ticket,'fingerprint':fingerprint(ticket),'execution_enabled':False}
        needed(args,'ledger')
        ledger=read_json(args.ledger)
        if ledger.get('mode')!='paper': raise ValueError('Only explicit simulation logs are supported.')
        return {'events':ledger.get('events',[]),'execution_enabled':False}
    if mode == 'alerts':
        if args.action == 'create':
            needed(args,'plan')
            return {'rules':alerts_from_plan(read_json(args.plan))}
        if args.action == 'clock':
            needed(args,'calendar','symbol')
            return Calendar(read_json(args.calendar),args.symbol).status(now)
        needed(args,'rules')
        rules = read_json(args.rules)['rules']
        if args.action=='add':
            needed(args,'rule')
            rule=read_json(args.rule)
            if rule['type'] not in ('above','below','pct_move','time','opening_bell'): raise ValueError('Unknown alert type.')
            symbol(rule['symbol'])
            if not rule.get('id') or any(r['id']==rule['id'] for r in rules): raise ValueError('Alert ID must be new and nonempty.')
            return {'rules':rules+[rule]}
        if args.action == 'list':
            return {'rules':rules,'state':state_read(args.state)}
        if args.action == 'reset':
            needed(args,'state','reset_id')
            state = {k:v for k,v in state_read(args.state).items() if not k.startswith(args.reset_id+':')}
            write_json(args.state,state,replace=True)
            return {'reset_id':args.reset_id,'state':state}
        needed(args,'calendar','symbol')
        quotes = read_json(args.quotes) if args.quotes else {}
        result = evaluate_alerts(rules,quotes,Calendar(read_json(args.calendar),args.symbol),now,state_read(args.state),integer(args.max_age,1,900))
        if args.state:
            write_json(args.state,result['state'],replace=True)
        return result
    if mode in ('backtest','timemachine'):
        plan = read_json(args.plan) if mode == 'timemachine' else None
        sym = plan['symbol'] if plan else args.symbol
        cal = Calendar(read_json(args.calendar),sym)
        _, bars, events, digest = chart(sym,'5m',args.offline,history=True)
        before = now_ist(plan['entry_at']).date() if plan else (dt.date.fromisoformat(args.before) if args.before else now.date())
        if before > now.date():
            raise ValueError('Research cutoff cannot exceed the as-of date.')
        sessions, excluded = history_sessions(bars,cal,before,now,events)
        if not sessions:
            raise ValueError('No complete verified sessions in dataset.')
        strategy = read_json(args.strategy) if args.strategy else None
        if mode == 'backtest':
            result = backtest(sessions,cal,strategy)
        else:
            # Confirm the plan's observed signal bar exists; never let future plan dates leak in.
            at = now_ist(plan['entry_at'])
            if at > now:
                raise ValueError('Plan entry is in the future.')
            spec = cal.get(at.date().isoformat())
            if spec['start'] != now_ist(plan['session_open']) or spec['end'] != now_ist(plan['session_end']) or spec['tick'] != number(plan['tick_size']):
                raise ValueError('Plan/calendar mismatch.')
            observed = __import__('pack_core').session_bars(bars,spec,at,5)
            if not observed or observed[-1]['start']+dt.timedelta(minutes=5) != at:
                raise ValueError('No complete entry confirmation bar.')
            result = {'monte_carlo':monte_carlo(sessions,plan,args.replays,args.seed,args.window)}
            if strategy is None and plan.get('setup')=='orb':
                stop_rule=plan.get('stop_rule','or-mid')
                if stop_rule not in ('or-mid','or-low') and not stop_rule.startswith('pct:'):
                    stop_rule='pct:'+str((number(plan['entry'])-number(plan['stop']))/number(plan['entry'])*100)
                strategy={'or_minutes':plan.get('or_minutes',15),'stop_rule':stop_rule,
                          'target_rule':str((number(plan['target'])-number(plan['entry']))/(number(plan['entry'])-number(plan['stop'])))+'R',
                          'flat_minutes_before_end':int((now_ist(plan['session_end'])-now_ist(plan['flat_by'])).total_seconds()/60)}
            if strategy:
                result['history'] = backtest(sessions,cal,strategy)
        result.update(data_fingerprint=digest,calendar_fingerprint=fingerprint(cal.doc),excluded_sessions=excluded,as_of=now.isoformat())
        return result
    if mode == 'chart':
        doc = read_json(args.input)
        mc = doc.get('monte_carlo',doc)
        bands = mc['bands']
        low, high = min(b[0] for b in bands),max(b[4] for b in bands)
        def pos(x):
            return min(59,max(0,round((x-low)/(high-low)*59))) if high>low else 30
        lines=[]
        for j in range(0,len(bands),max(1,len(bands)//16)):
            band=bands[j]
            line=[' ']*60
            a,b=pos(band[0]),pos(band[4])
            for i in range(a,b+1): line[i]='-'
            line[pos(band[2])]='*'
            lines.append(str(j*5)+'m '+''.join(line))
        return {'chart':'\n'.join(lines),'low_inr':low,'high_inr':high,'legend':'IST; * median, - 5th to 95th simulated price percentiles'}
    if mode == 'news':
        text = read_text(args.offline) if args.offline else public_get(FEEDS[args.feed])
        result = parse_feed(text,FEEDS[args.feed],args.query,args.since,state_read(args.state))
        if args.state:
            write_json(args.state,result['state'],replace=True)
        if args.new_only:
            result['items']=[item for item in result['items'] if item['new']]
        return result
    if mode == 'analyst':
        return financial_analysis(read_json(args.input))
    if mode == 'disclosures':
        result=disclosures(read_json(args.input),state_read(args.state))
        if args.state:
            write_json(args.state,result['state'],replace=True)
        return result
    raise ValueError('Unknown command.')


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if getattr(args,'state',None) and args.output and Path(args.state).resolve() == Path(args.output).resolve():
            raise ValueError('State and report output must use different paths.')
        result=run(args)
        if args.output:
            write_json(args.output,result)
        print(json.dumps(result,indent=2,allow_nan=False))
        return 2 if result.get('errors') or result.get('failed') or result.get('status') == 'BLOCK' else 0
    except (ValueError,KeyError,TypeError,IndexError,OSError,ArithmeticError) as exc:
        print(json.dumps({'error':str(exc),'command':args.command}),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())

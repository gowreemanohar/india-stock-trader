"""Parity extensions: batch ORB, move checks, financial XBRL and CSV disclosure import."""
import argparse
import csv
import datetime as dt
from decimal import Decimal
import io
import json
import sys
import time
import xml.etree.ElementTree as ET

from pack_core import Calendar, chart, fingerprint, now_ist, number, integer, symbol, read_json, read_text, public_get, write_json
from trading import entry_check, risk_check, exit_plan
from research import financial_analysis, disclosures


def batch_entry(doc, now, offline=None, limit=50, offset=0):
    """Explicit per-symbol calendars; no ambient holdings/project lookups."""
    limit,offset=integer(limit,1,50),integer(offset,0,100000)
    rows,errors=[],[]
    selected=doc['items'][offset:offset+limit]
    for index,item in enumerate(selected):
        try:
            sym=symbol(item['symbol'])
            cal=Calendar(item['calendar'],sym)
            if index and not offline: time.sleep(.4)
            _,bars,_,digest=chart(sym,'5m',offline)
            result=entry_check(sym,bars,cal,now,or_minutes=item.get('or_minutes',15),level=item.get('level'),
                               min_volume_x=item.get('min_volume_x',0),no_entries_before=item.get('no_entries_before'),
                               no_entries_after=item.get('no_entries_after'))
            rows.append(dict(result,data_fingerprint=digest))
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append({'symbol':item.get('symbol'),'error':str(exc)})
    return {'requested':len(selected),'universe_count':len(doc['items']),'offset':offset,'succeeded':len(rows),
            'failed':len(errors),'partial':bool(errors) or len(selected)<len(doc['items']),
            'hits':[r for r in rows if r.get('status') in ('triggered','triggered_earlier')],'rows':rows,'errors':errors}


def moves(symbols, now, threshold=3, offline=None):
    rows,errors=[],[]
    threshold=float(number(threshold,positive=True))
    if not 1<=len(symbols)<=50: raise ValueError('Moves accepts 1-50 explicit symbols.')
    for index,sym in enumerate(symbols):
        try:
            sym=symbol(sym)
            if index and not offline: time.sleep(.4)
            meta,bars,_,_=chart(sym,'1d',offline)
            stamp=dt.datetime.fromtimestamp(float(number(meta['regularMarketTime'])),now.tzinfo)
            if stamp>now: raise ValueError('Quote is after the as-of clock.')
            price=float(number(meta['regularMarketPrice'],positive=True))
            prior=[b for b in bars if b['start'].date()<stamp.date()]
            if not prior: raise ValueError('No prior-day reference close.')
            previous=prior[-1]
            change=(price/previous['close']-1)*100
            rows.append({'symbol':sym,'price_inr':price,'quoted_at':stamp.isoformat(),'age_seconds':int((now-stamp).total_seconds()),
                         'reference_close_inr':previous['close'],'reference_date':previous['start'].date().isoformat(),
                         'change_percent':change,'moving':abs(change)>=threshold,'source':'Yahoo unofficial; not verified real time'})
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append({'symbol':sym,'error':str(exc)})
    return {'rows':rows,'errors':errors,'threshold_percent':threshold,'as_of':now.isoformat()}


def xbrl_financials(xml, mapping):
    """Explicit taxonomy mapping avoids assuming Indian tags equal US-GAAP tags.

    Mapping fields: symbol, scope, source_url, filed_at, metrics {output: expanded-tag},
    context_ids [explicit verified standalone/consolidated contexts].
    """
    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise ValueError('Entity/DOCTYPE declarations are refused.')
    try: root=ET.fromstring(xml)
    except ET.ParseError as exc: raise ValueError('Malformed XBRL XML.') from exc
    ns={'x':'http://www.xbrl.org/2003/instance'}
    contexts={c.attrib['id']:c for c in root.findall('x:context',ns)}
    units={u.attrib['id']:[(n.text or '').strip() for n in u.iter() if n.tag.endswith('measure')] for u in root.findall('x:unit',ns)}
    reverse={tag:key for key,tag in mapping['metrics'].items()}
    allowed={'revenue','operating_profit','pat','operating_cash_flow','debt','cash','exceptional_items','eps'}
    if set(reverse.values())-allowed: raise ValueError('Unsupported financial output metric.')
    selected=mapping['context_ids']
    if not selected or len(set(selected))!=len(selected): raise ValueError('Choose unique explicit XBRL contexts.')
    periods=[]
    for context_id in selected:
        context=contexts[context_id]
        start=context.findtext('x:period/x:startDate',namespaces=ns)
        end=context.findtext('x:period/x:endDate',namespaces=ns)
        if not start or not end: raise ValueError('Selected financial context must be a duration quarter, not an instant.')
        row={'start':start,'end':end,'filed_at':mapping['filed_at'],'source_url':mapping['source_url'],
             'scope':mapping['scope'],'unit':'INR'}
        seen=set()
        for node in root.iter():
            key=reverse.get(node.tag)
            if key is None or node.attrib.get('contextRef')!=context_id: continue
            if key in seen: raise ValueError('Duplicate facts for selected metric/context; resolve restatements explicitly.')
            if node.attrib.get('{http://www.w3.org/2001/XMLSchema-instance}nil') in ('true','1'): continue
            seen.add(key)
            measures=units.get(node.attrib.get('unitRef'),[])
            currency=any(v.split(':')[-1]=='INR' for v in measures)
            shares=any(v.split(':')[-1]=='shares' for v in measures)
            if not currency or (key=='eps' and not shares) or (key!='eps' and shares):
                raise ValueError('XBRL fact currency/unit does not match expected INR or INR/share.')
            # XBRL decimals is precision, not a scaling multiplier.
            val=number((node.text or '').strip(),minimum=Decimal('-1e30'))
            row[key]=str(val)
        periods.append(row)
    normalized={'symbol':symbol(mapping['symbol']),'scope':mapping['scope'],'periods':periods}
    result=financial_analysis(normalized)
    result['normalized_input']=normalized
    result['context_selection_note']='Caller explicitly verified contexts, taxonomy mapping and consolidation scope.'
    return result


def disclosure_csv(text,mapping):
    records=[]
    for raw in csv.DictReader(io.StringIO(text)):
        row=dict(mapping.get('constants',{}))
        for output,column in mapping['columns'].items():
            value=raw[column].strip()
            row[output]=value if value else None
        records.append(row)
    return disclosures({'records':records})


def batch_risk(doc, calendar_docs, now):
    """Reserve each accepted ticket's risk/cash/exposure before evaluating the next."""
    account=json.loads(json.dumps(doc['account']))
    results=[]
    for ticket in doc['tickets']:
        sym=ticket['plan']['symbol']
        verdict=risk_check(ticket,doc['limits'],account,doc['quotes'][sym],Calendar(calendar_docs[sym],sym),now)
        results.append(verdict)
        if verdict['status']=='PASS_RESEARCH':
            qty=integer(ticket['quantity'],1)
            entry=number(verdict['evaluated_entry_inr'])
            cost=number(ticket['plan']['cost_per_share'])
            account['cash']=str(number(account['cash'])-qty*(entry+cost))
            account['open_risk']=str(number(account['open_risk'])+number(verdict['planned_loss_inr']))
            account['trades_today']=integer(account['trades_today'])+1
            if 'orders_today' in account: account['orders_today']=integer(account['orders_today'])+1
            account['entered_symbols_today']=account.get('entered_symbols_today',[])+[sym]
            old=account.setdefault('positions',{}).get(sym,{'quantity':0,'market_value':'0'})
            account['positions'][sym]={'quantity':integer(old['quantity'])+qty,'market_value':str(number(old['market_value'])+qty*entry)}
    return {'status':'PASS_RESEARCH' if all(r['status']=='PASS_RESEARCH' for r in results) else 'BLOCK',
            'results':results,'reserved_account_projection':account,'execution_enabled':False,
            'note':'Batch reservations are conservative projections, not fillable paper ledgers. Recheck individual tickets against the actual current ledger before each simulated fill.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['orb','watchlist','moves','xbrl','disclosure-csv','risk-batch','entry-replay','plan','paper-log'])
    for key in ('input','mapping','url','offline','symbols','calendars','now','output'):
        p.add_argument('--'+key)
    p.add_argument('--limit',type=int,default=50)
    p.add_argument('--offset',type=int,default=0)
    p.add_argument('--move-pct',type=float,default=3)
    args=p.parse_args(argv)
    try:
        now=now_ist(args.now)
        if args.action in ('orb','watchlist'):
            if not args.input: raise ValueError('--input batch manifest required.')
            result=batch_entry(read_json(args.input),now,args.offline,args.limit,args.offset)
        elif args.action=='moves':
            if not args.symbols: raise ValueError('--symbols required.')
            result=moves(args.symbols.split(','),now,args.move_pct,args.offline)
        elif args.action=='xbrl':
            if not args.mapping or bool(args.input)==bool(args.url): raise ValueError('Provide --mapping and exactly one of --input or --url.')
            result=xbrl_financials(read_text(args.input) if args.input else public_get(args.url),read_json(args.mapping))
        elif args.action=='disclosure-csv':
            if not args.input or not args.mapping: raise ValueError('--input CSV and --mapping JSON required.')
            result=disclosure_csv(read_text(args.input),read_json(args.mapping))
        elif args.action=='risk-batch':
            if not args.input or not args.calendars: raise ValueError('--input and --calendars required.')
            result=batch_risk(read_json(args.input),read_json(args.calendars),now)
        elif args.action=='entry-replay':
            if not args.input: raise ValueError('--input manifest with symbol/calendar/date required.')
            doc=read_json(args.input)
            sym=symbol(doc['symbol'])
            cal=Calendar(doc['calendar'],sym)
            spec=cal.get(doc['date'])
            _,bars,_,digest=chart(sym,'5m',args.offline)
            if spec['end']>now: raise ValueError('Historical replay requires a completed session.')
            states=[]
            moment=spec['start']+dt.timedelta(minutes=5)
            while moment<=spec['end']:
                states.append(entry_check(sym,bars,cal,moment,doc['date'],or_minutes=doc.get('or_minutes',15),
                                          level=doc.get('level'),min_volume_x=doc.get('min_volume_x',0)))
                moment+=dt.timedelta(minutes=5)
            result={'states':states,'data_fingerprint':digest,'historical_replay':True}
        elif args.action=='plan':
            if not args.input: raise ValueError('--input explicit hypothetical entry and stop/target parameters required.')
            doc=read_json(args.input)
            result=exit_plan(doc['entry'],doc['stop_rule'],doc['target_rule'],doc['flat_by'])
            result['hypothetical_manual_entry']=True
        elif args.action=='paper-log':
            if not args.input: raise ValueError('--input paper ledger required.')
            doc=read_json(args.input)
            if doc.get('mode')!='paper': raise ValueError('Only paper ledgers supported.')
            result={'events':doc.get('events',[]),'positions':doc.get('positions',{}),'cash':doc['cash'],'execution_enabled':False}
        if args.output: write_json(args.output,result)
        print(json.dumps(result,indent=2,allow_nan=False))
        return 2 if result.get('errors') or result.get('status')=='BLOCK' else 0
    except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())

"""Original Time Machine rules adapted only for Indian sessions and tick sizes."""
import datetime as dt
import statistics
from decimal import Decimal
from pack_core import integer, number, now_ist, session_bars, tick_price, validate_plan, fingerprint
from upstream_simulation import simulate, verdict, verdict_notes


def history_sessions(bars,calendar,before,now,events=None):
    grouped={}
    for b in bars: grouped.setdefault(b['start'].date().isoformat(),[]).append(b)
    sessions,excluded=[],[]
    for day in sorted(set(grouped)|set(calendar.sessions)):
        if dt.date.fromisoformat(day)>=before: continue
        if day in calendar.sessions and calendar.sessions[day] is None: continue
        try:
            spec=calendar.get(day)
            rows=session_bars(grouped.get(day,[]),spec,now,5,require_full=True)
            sessions.append({'date':day,'bars':rows,'spec':spec})
        except ValueError as exc: excluded.append({'date':day,'reason':str(exc)})
    return sessions,excluded


def no_extra_cost_model(doc):
    if number(doc.get('cost_per_share',0)) or number(doc.get('slippage_bps',0)):
        raise ValueError('Original-pack parity: costs/slippage are not modeled; remove nonzero settings.')


def replay_path(bars,entry,stop,target):
    if not bars or not 0<stop<entry<target: raise ValueError('Need bars and stop < entry < target.')
    outcome,fill='close',bars[-1]['close']
    for b in bars:
        if b['low']<=stop:
            outcome,fill='stop',stop
            break
        if b['high']>=target:
            outcome,fill='target',target
            break
    return {'outcome':outcome,'R':(fill-entry)/(entry-stop)}


def summarize(trades):
    return {'triggered':len(trades),'target':sum(t['outcome']=='target' for t in trades),
            'stop':sum(t['outcome']=='stop' for t in trades),'close':sum(t['outcome']=='close' for t in trades),
            'green':sum(t['R']>0 for t in trades),'avg_R':round(statistics.mean(t['R'] for t in trades),3) if trades else None}


def session_trade(item,calendar,strategy):
    no_extra_cost_model(strategy)
    minutes=integer(strategy.get('or_minutes',15),5,120)
    if minutes%5: raise ValueError('Opening range must align to five-minute bars.')
    rows,spec=item['bars'],item['spec']
    n=minutes//5
    flat=spec['end']-dt.timedelta(minutes=integer(strategy.get('flat_minutes_before_end',0),0,120))
    count=int((flat-spec['start']).total_seconds()//300)
    if count<=n or count>len(rows): raise ValueError('Invalid replay cutoff/range.')
    high=max(b['high'] for b in rows[:n]); low=min(b['low'] for b in rows[:n])
    k=next((i for i in range(n,count) if rows[i]['close']>high),None)
    if k is None: return None
    e=tick_price(rows[k]['close'],spec['tick'],up=True)
    rule=strategy.get('stop_rule','or-mid')
    if rule=='or-mid': s=(Decimal(str(high))+Decimal(str(low)))/2
    elif rule=='or-low': s=Decimal(str(low))
    elif rule.startswith('pct:'): s=e*(1-number(rule[4:],positive=True)/100)
    else: raise ValueError('Historical stop rules: or-mid, or-low, pct:X.')
    s=tick_price(s,spec['tick'])
    if s>=e: return None
    target=strategy.get('target_rule','2R')
    if not target.endswith('R'): raise ValueError('Historical target must be XR.')
    t=tick_price(e+number(target[:-1],positive=True)*(e-s),spec['tick'],up=True)
    following=rows[k+1:count]
    result=replay_path(following,float(e),float(s),float(t)) if following else {'outcome':'close','R':0.0}
    return dict(result,date=item['date'],time=(rows[k]['start']+dt.timedelta(minutes=5)).isoformat(),
                entry=float(e),stop=float(s),target=float(t),entry_model='signal_bar_close')


def backtest(sessions,calendar,strategy):
    trades=[]
    for item in sessions:
        trade=session_trade(item,calendar,strategy)
        if trade: trades.append(trade)
    return {'schema':'india-history-parity-v1','symbol':calendar.symbol,'sessions':len(sessions),'rule':strategy,
            'summary':summarize(trades),'trades':trades,
            'note':'Original assumptions: confirmation-close entry, no fees/slippage, stop touch is -1R even on gaps. Real fills can be worse.'}


def monte_carlo(sessions,plan,replays=10000,seed=19,window=2,min_sessions=20):
    no_extra_cost_model(plan)
    e,s,t=map(float,validate_plan(plan))
    replays=integer(replays,1,50000); window=integer(window,0,12)
    start,at,flat,end=[now_ist(plan[key]) for key in ('session_open','entry_at','flat_by','session_end')]
    if plan['interval_minutes']!=5 or any((v-start).total_seconds()%300 for v in (at,flat,end)):
        raise ValueError('Simulation requires aligned five-minute bars.')
    count=int((end-start).total_seconds()/300)
    k=int((at-start).total_seconds()/300)-1; last=int((flat-start).total_seconds()/300)-1
    if not 0<=k<last<count: raise ValueError('Entry must leave bars to replay.')
    compatible=sorted((item for item in sessions if dt.date.fromisoformat(item['date'])<at.date()
                       and item['spec']['start'].time()==start.time() and item['spec']['end'].time()==end.time()
                       and len(item['bars'])==count),key=lambda item:item['date'])
    if len(compatible)<max(20,min_sessions):
        raise ValueError(f'Need at least {max(20,min_sessions)} complete prior same-regime sessions; got {len(compatible)}.')
    pool=[[] for _ in range(count)]
    for item in compatible:
        rows=item['bars']
        for j in range(1,count):
            previous=rows[j-1]['close']
            pool[j].append(tuple(rows[j][key]/previous for key in ('open','high','low','close')))
    result=simulate(pool,e,s,t,k,last,replays,seed,window,session_bars=count)
    result.update(schema='india-monte-carlo-parity-v1',symbol=plan['symbol'],prior_sessions=len(compatible),
                  pool_last_date=compatible[-1]['date'],until=flat.strftime('%H:%M'),plan_fingerprint=fingerprint(plan))
    result['verdict']=verdict(result); result['verdict_notes']=verdict_notes(result)
    result['note']='Original resampling/R mathematics. No trained forecast, costs or slippage; gap stops count -1R. Real fills can be worse.'
    return result

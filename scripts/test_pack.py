"""Behavioral, financial-invariant and complete offline CLI tests. Synthetic data only."""
import contextlib
import copy
import datetime as dt
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pack
from pack_core import Calendar, fingerprint, now_ist, validate_plan, write_json, public_get
from trading import entry_check, exit_plan, budget, allocate, risk_check, alerts_from_plan, evaluate_alerts
from simulation import history_sessions, backtest, monte_carlo, replay_path
from research import universe, parse_feed, financial_analysis, disclosures


def synthetic():
    """31 weekday sessions, 09:15-10:15, explicitly synthetic shortened schedule."""
    days=[]
    date=dt.date(2026,9,1)
    while len(days)<31:
        if date.weekday()<5:
            days.append(date.isoformat())
        date+=dt.timedelta(days=1)
    doc={'symbol':'TEST.NS','timezone':'Asia/Kolkata','source_url':'https://example.com/SYNTHETIC-NOT-A-MARKET-CALENDAR',
         'verified_at':'2026-10-20T12:00:00+05:30',
         'sessions':{day:{'open':'09:15','end':'10:15','tick_size':'0.05'} for day in days}}
    bars=[]
    for i,day in enumerate(days):
        start=now_ist(day+'T09:15')
        for k in range(12):
            price=101 if k<3 else 103
            high=102 if k<3 else 104
            low=100 if k<3 else 102
            if k>=5:
                if i%3==0: high=110
                elif i%3==1: low=98
            bars.append({'start':start+dt.timedelta(minutes=5*k),'open':price,'high':high,'low':low,'close':price,'volume':10000})
    quotes={k:[b[k] for b in bars] for k in ('open','high','low','close','volume')}
    yahoo={'chart':{'error':None,'result':[{'meta':{'symbol':'TEST.NS','currency':'INR','instrumentType':'EQUITY','dataGranularity':'5m'},
              'timestamp':[b['start'].timestamp() for b in bars],'indicators':{'quote':[quotes]}}]}}
    strategy={'or_minutes':15,'stop_rule':'or-mid','target_rule':'2R','flat_minutes_before_end':5,
              'cost_per_share':'0','slippage_bps':'0'}
    cal=Calendar(doc,'TEST.NS')
    now=now_ist(days[-1]+'T09:35')
    entry=entry_check('TEST.NS',bars,cal,now)
    plan=exit_plan(entry,'or-mid','2R','10:10','0','0')
    limits={'max_order':'50000','min_order':'100','max_position':'50000','cash_buffer':'1000',
            'max_loss_per_trade':'1000','max_daily_loss':'3000','min_reward_risk':'1',
            'max_trades_per_day':3,'max_quote_age_seconds':60,'max_account_age_seconds':60,
            'no_entries_before':'09:30','no_entries_after':'10:00','blocked_symbols':[]}
    account={'cash':'100000','positions':{},'as_of':now.isoformat(),'realized_loss_today':'0',
             'open_risk':'0','trades_today':0,'entered_symbols_today':[]}
    quote={'symbol':'TEST.NS','currency':'INR','price':'103','quoted_at':now.isoformat(),'restrictions_checked':True}
    return doc,cal,bars,yahoo,strategy,entry,plan,limits,account,quote,now


class PackTests(unittest.TestCase):
    def setUp(self):
        (self.doc,self.cal,self.bars,self.yahoo,self.strategy,self.entry,self.plan,self.limits,self.account,self.quote,self.now)=synthetic()

    def test_unknown_holiday_and_wrong_symbol_fail(self):
        with self.assertRaises(ValueError): self.cal.get('2027-01-01')
        with self.assertRaises(ValueError): Calendar(self.doc,'OTHER.NS')
        self.doc['sessions']['2026-10-31']={'closed':True}
        self.assertEqual(Calendar(self.doc,'TEST.NS').status(now_ist('2026-10-31T09:30'))['status'],'closed')

    def test_entry_states_and_volume(self):
        day=self.now.date().isoformat()
        self.assertEqual(entry_check('TEST.NS',self.bars,self.cal,now_ist(day+'T09:10'))['status'],'not_open')
        self.assertEqual(entry_check('TEST.NS',self.bars,self.cal,now_ist(day+'T09:25'))['status'],'range_forming')
        self.assertEqual(self.entry['status'],'triggered')
        self.assertEqual(entry_check('TEST.NS',self.bars,self.cal,self.now,min_volume_x=2)['status'],'waiting')
        self.assertEqual(entry_check('TEST.NS',self.bars,self.cal,self.now,level='105')['status'],'waiting')
        self.assertEqual(entry_check('TEST.NS',self.bars,self.cal,now_ist(day+'T10:15'))['status'],'expired')

    def test_tick_and_stop_rules(self):
        for rule in ('or-mid','or-low','pct:1','price:100','atr:1.5'):
            p=exit_plan(self.entry,rule,'2R','10:10','0','0',self.bars)
            validate_plan(p)
            self.assertEqual(Decimal(p['stop'])%Decimal('0.05'),0)
        with self.assertRaises(ValueError): exit_plan(self.entry,'price:104','2R','10:10','0','0')
        with self.assertRaises(ValueError): exit_plan(self.entry,'or-mid','2R','09:30','0','0')

    def test_budget_and_risk_recompute_tampered_totals(self):
        ticket=budget(self.plan,self.limits,self.account)
        self.assertGreater(ticket['quantity'],0)
        result=risk_check(ticket,self.limits,self.account,self.quote,self.cal,self.now)
        self.assertEqual(result['status'],'PASS_RESEARCH')
        ticket['quantity']=100000
        ticket['planned_loss_inr']='0'
        self.assertEqual(risk_check(ticket,self.limits,self.account,self.quote,self.cal,self.now)['status'],'BLOCK')

    def test_risk_stale_daily_limit_and_duplicates(self):
        ticket=budget(self.plan,self.limits,self.account)
        for key,value in [('realized_loss_today','3000'),('open_risk','3000'),('trades_today',3),('entered_symbols_today',['TEST.NS'])]:
            account=dict(self.account,**{key:value})
            self.assertEqual(risk_check(ticket,self.limits,account,self.quote,self.cal,self.now)['status'],'BLOCK')
        stale=dict(self.quote,quoted_at=(self.now-dt.timedelta(minutes=10)).isoformat())
        self.assertEqual(risk_check(ticket,self.limits,self.account,stale,self.cal,self.now)['status'],'BLOCK')

    def test_weight_allocation_caps_and_cash(self):
        result=allocate({'TEST.NS':9,'OTHER.BO':1},{'TEST.NS':100,'OTHER.BO':50},10000,3000,1000)
        self.assertTrue(all(Decimal(r['notional_inr'])<=3000 for r in result['allocations']))
        self.assertEqual(Decimal(result['unallocated_cash_inr']),4000)


    def test_alert_once_rearm_stale_and_time(self):
        rules=alerts_from_plan(self.plan)
        q=dict(self.quote,price=self.plan['target'])
        result=evaluate_alerts(rules,{'TEST.NS':q},self.cal,self.now)
        self.assertEqual(len(result['alerts']),1)
        self.assertFalse(evaluate_alerts(rules,{'TEST.NS':q},self.cal,self.now,result['state'])['alerts'])
        q['quoted_at']=(self.now-dt.timedelta(hours=1)).isoformat()
        self.assertTrue(evaluate_alerts(rules,{'TEST.NS':q},self.cal,self.now)['errors'])
        after=now_ist(self.plan['flat_by'])
        self.assertTrue(any(a['type']=='time' for a in evaluate_alerts(rules,{},self.cal,after)['alerts']))


    def test_future_sessions_excluded_and_gaps_reported(self):
        sessions,excluded=history_sessions(self.bars,self.cal,self.now.date(),self.now)
        self.assertEqual(len(sessions),30)
        self.assertTrue(all(dt.date.fromisoformat(s['date'])<self.now.date() for s in sessions))
        fewer,excluded=history_sessions(self.bars[1:],self.cal,self.now.date(),self.now)
        self.assertEqual(len(fewer),29)
        self.assertEqual(len(excluded),1)




    def test_universe_and_feed_inputs(self):
        text='SYMBOL,NAME OF COMPANY,SERIES,MARKET LOT,ISIN NUMBER\nTEST,Test Ltd,EQ,1,INE123456789\nOTHER,Other Ltd,BE,1,INE987654321\n'
        u=universe(text)
        self.assertEqual((u['count'],u['skipped']),(1,1))
        rss='<rss><channel><item><title>Test Limited</title><link>https://www.nseindia.com/test</link><description>Quarterly financial results</description><pubDate>Fri, 30 Oct 2026 15:00:00 +0530</pubDate></item></channel></rss>'
        r=parse_feed(rss,'fixture',query='Test Limited')
        self.assertIn('earnings',r['items'][0]['tags'])
        self.assertFalse(parse_feed(rss,'fixture',seen=r['state'])['items'][0]['new'])
        with self.assertRaises(ValueError): parse_feed('<!DOCTYPE rss><rss/>','fixture')
        with self.assertRaises(ValueError): parse_feed('<html>Denied</html>','fixture')

    def test_financial_units_eps_and_scope(self):
        periods=[]
        for year,unit,rev,pat in [(2025,'lakh',1000,100),(2026,'crore',12,1.2)]:
            periods.append({'start':f'{year}-07-01','end':f'{year}-09-30','filed_at':f'{year}-10-20T10:00:00+05:30',
                            'source_url':'https://www.nseindia.com/filing','unit':unit,'revenue':rev,'pat':pat,'eps':2})
        doc={'symbol':'TEST.NS','scope':'consolidated','periods':periods}
        out=financial_analysis(doc)
        self.assertEqual(Decimal(out['periods'][1]['yoy_percent']['revenue']),20)
        self.assertEqual(out['periods'][1]['metrics_inr_except_eps']['eps'],'2')
        doc['periods'][1]['scope']='standalone'
        with self.assertRaises(ValueError): financial_analysis(doc)

    def test_disclosure_dates_and_values(self):
        doc={'records':[{'symbol':'TEST.NS','category':'promoter','person_or_entity':'Example Person',
                         'event_date':'2026-10-20','filed_at':'2026-10-23T10:00:00+05:30',
                         'source_url':'https://www.nseindia.com/filing','quantity':100,'value_inr':None}]}
        result=disclosures(doc)
        self.assertEqual(result['records'][0]['reporting_delay_days'],3)
        self.assertIsNone(result['records'][0]['value_inr'])
        self.assertFalse(disclosures(doc,result['state'])['records'][0]['new'])

    def test_no_arbitrary_network_or_overwrites(self):
        with self.assertRaises(ValueError): public_get('http://127.0.0.1/secrets')
        with tempfile.TemporaryDirectory(prefix='india-pack-test-') as temp:
            p=Path(temp)/'result.json'
            write_json(p,{'ok':True})
            with self.assertRaises(FileExistsError): write_json(p,{'ok':False})



if __name__=='__main__':
    unittest.main()

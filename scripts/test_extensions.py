import contextlib
import datetime as dt
import gzip
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import extensions
from pack_core import now_ist, read_json
from test_pack import synthetic
from trading import budget


def daily_fixture(count=700):
    bars=[]
    day=dt.date(2022,1,3)
    price=100.0
    while len(bars)<count:
        if day.weekday()<5:
            i=len(bars)
            price*=1+(.006 if i%5<3 else -.007)+.002*math.sin(i)
            bars.append({'start':now_ist(day.isoformat()+'T09:15'),'open':price,'high':price*1.01,
                         'low':price*.99,'close':price,'volume':10000+100*(i%17)})
        day+=dt.timedelta(days=1)
    return bars


class ExtensionTests(unittest.TestCase):
    def test_gzip_offline(self):
        with tempfile.TemporaryDirectory(prefix='india-gzip-') as folder:
            path=Path(folder)/'input.json.gz'
            with gzip.open(path,'wt',encoding='utf-8') as stream: json.dump({'test':True},stream)
            self.assertEqual(read_json(path),{'test':True})

    def test_batch_orb_and_move_reference(self):
        doc,cal,bars,yahoo,strategy,entry,plan,limits,account,quote,now=synthetic()
        with patch('extensions.chart',return_value=({},bars,{},'hash')):
            report=extensions.batch_entry({'items':[{'symbol':'TEST.NS','calendar':doc}]},now)
            self.assertEqual(report['hits'][0]['status'],'triggered')
        daily=daily_fixture(30)
        stamp=daily[-1]['start']+dt.timedelta(hours=6)
        meta={'regularMarketPrice':daily[-2]['close']*1.04,'regularMarketTime':stamp.timestamp()}
        with patch('extensions.chart',return_value=(meta,daily,{},'hash')):
            result=extensions.moves(['TEST.NS'],stamp+dt.timedelta(minutes=1))
            self.assertAlmostEqual(result['rows'][0]['change_percent'],4)
            self.assertTrue(result['rows'][0]['moving'])

    def test_batch_risk_reserves_prior_ticket(self):
        doc,cal,bars,yahoo,strategy,entry,plan,limits,account,quote,now=synthetic()
        ticket=budget(plan,limits,account)
        report=extensions.batch_risk({'tickets':[ticket,ticket],'limits':limits,'account':account,'quotes':{'TEST.NS':quote}},
                                    {'TEST.NS':doc},now)
        self.assertEqual(report['results'][0]['status'],'PASS_RESEARCH')
        self.assertEqual(report['results'][1]['status'],'BLOCK')

    def test_xbrl_units_context_and_decimals(self):
        xml='''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:in="urn:ind-as" xmlns:iso="http://www.xbrl.org/2003/iso4217">
        <context id="Q"><entity><identifier scheme="test">test</identifier></entity><period><startDate>2026-07-01</startDate><endDate>2026-09-30</endDate></period></context>
        <unit id="rupees"><measure>iso:INR</measure></unit>
        <in:Revenue contextRef="Q" unitRef="rupees" decimals="-6">120000000</in:Revenue>
        <in:Pat contextRef="Q" unitRef="rupees" decimals="-6">12000000</in:Pat></xbrl>'''
        mapping={'symbol':'TEST.NS','scope':'consolidated','filed_at':'2026-10-20T10:00:00+05:30','source_url':'https://www.nseindia.com/test',
                 'context_ids':['Q'],'metrics':{'revenue':'{urn:ind-as}Revenue','pat':'{urn:ind-as}Pat'}}
        result=extensions.xbrl_financials(xml,mapping)
        self.assertEqual(result['periods'][0]['metrics_inr_except_eps']['revenue'],'120000000')
        self.assertEqual(result['periods'][0]['pat_margin_percent'],'10.0')
        with self.assertRaises(ValueError): extensions.xbrl_financials(xml.replace('iso:INR','iso:USD'),mapping)

    def test_extension_cli_replay_plan_log(self):
        doc,cal,bars,yahoo,strategy,entry,plan,limits,account,quote,now=synthetic()
        with tempfile.TemporaryDirectory(prefix='india-extension-cli-') as folder:
            root=Path(folder)
            def run(action,value,at=None):
                path=root/(action+'.json')
                path.write_text(json.dumps(value),encoding='utf-8')
                stream=io.StringIO()
                with patch('extensions.chart',return_value=({},bars,{},'synthetic')),contextlib.redirect_stdout(stream):
                    code=extensions.main([action,'--input',str(path),'--now',(at or now).isoformat()])
                self.assertEqual(code,0,stream.getvalue())
                return json.loads(stream.getvalue())
            result=run('entry-replay',{'symbol':'TEST.NS','calendar':doc,'date':now.date().isoformat()},now+dt.timedelta(hours=2))
            self.assertTrue(any(row['status']=='triggered' for row in result['states']))
            result=run('plan',{'entry':entry,'stop_rule':'or-mid','target_rule':'2R','flat_by':'10:10','cost_per_share':'0.2','slippage_bps':'2'})
            self.assertTrue(result['hypothetical_manual_entry'])
            ledger={'mode':'paper','currency':'INR','cash':'1000','positions':{'TEST.NS':{'quantity':1,'entry':'103','entry_cost':'0.1',
                        'opened_at':now.isoformat(),'plan':plan}},'events':[],'as_of':now.isoformat()}
            self.assertEqual(run('paper-log',ledger)['cash'],'1000')


if __name__=='__main__': unittest.main()

"""Direct behavioral comparison with inspected original pure mathematical functions."""
import ast
import contextlib
import datetime as dt
import io
import json
import math
from pathlib import Path
import random
import statistics
import tempfile
import unittest

import pack
from pack_core import now_ist,write_json
from simulation import history_sessions,backtest,monte_carlo,replay_path
from upstream_simulation import simulate
from research import financial_analysis
from test_pack import synthetic


def original_functions(names):
    path=Path(__file__).resolve().parents[2]/'trader-timemachine'/'timemachine.py'
    if not path.exists(): raise unittest.SkipTest('Optional original installation unavailable for direct comparison.')
    source=path.read_text(encoding='utf-8')
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in names]
    scope={'random':random,'statistics':statistics,'math':math,'SESSION_BARS':78,'OPEN_MIN':9*60+15,
           'SAMPLE_PATHS':160,'BAND_PATHS':2000,'BAND_Q':(.05,.25,.5,.75,.95),'HIST_BINS':24}
    # Only explicitly selected, reviewed pure mathematics; no original I/O or main is loaded.
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope)
    return scope


class OriginalParityTests(unittest.TestCase):
    def test_daily_current_bar_only_after_verified_close(self):
        from india_trader import daily
        now=now_ist('2026-10-30T16:00')
        rows=[{'start':now-dt.timedelta(days=31-i),'close':100+i,'volume':1000} for i in range(32)]
        self.assertEqual(daily(rows,now,0,0)['close_inr'],130)
        self.assertEqual(daily(rows,now,0,0,today_complete=True)['close_inr'],131)

    def test_monte_carlo_exact_original_rng_and_statistics(self):
        original=original_functions({'pct','simulate'})
        for count in (12,72,78):
            pool=[[]]+[[(1,1.012,.991,1.003),(1.001,1.008,.984,.996),(1,.999,.989,.992)] for _ in range(1,count)]
            original['SESSION_BARS']=count
            for seed in (7,19):
                expected=original['simulate'](pool,100,98,104,3,count-1,200,seed,2)
                actual=simulate(pool,100,98,104,3,count-1,200,seed,2,session_bars=count)
                self.assertEqual(actual,expected)

    def test_historical_entry_and_outcomes_match_original(self):
        doc,cal,bars,yahoo,strategy,entry,plan,limits,account,quote,now=synthetic()
        sessions,_=history_sessions(bars,cal,now.date(),now)
        adapted=backtest(sessions,cal,strategy)
        original=original_functions({'cents_away','opening_range','rule_stop','history_replay','clock12'})
        rows=[(item['date'],[{'o':b['open'],'h':b['high'],'l':b['low'],'c':b['close']} for b in item['bars']]) for item in sessions]
        reference=original['history_replay'](rows,{'or_minutes':15,'stop_rule':'or_mid','target_r':2},10)
        for key in ('triggered','target','stop','close','green','avg_R'):
            self.assertEqual(adapted['summary'][key],reference[key])
        self.assertEqual([t['entry'] for t in adapted['trades']],[t['entry'] for t in reference['trades']])

    def test_original_gap_and_both_touch_assumption(self):
        bar={'low':89,'high':120,'close':99,'open':90}
        self.assertEqual(replay_path([bar],100,95,110),{'outcome':'stop','R':-1.0})

    def test_no_added_cli_modes(self):
        for args in (['walkforward'],['paper','fill'],['paper','init'],['paper','close']):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit): pack.parser().parse_args(args)

    def test_automatic_history_and_ten_thousand_replays(self):
        doc,cal,bars,yahoo,strategy,entry,plan,limits,account,quote,now=synthetic()
        with tempfile.TemporaryDirectory(prefix='india-parity-') as folder:
            base=Path(folder)
            for name,value in [('calendar',doc),('chart',yahoo),('plan',plan)]: write_json(base/(name+'.json'),value)
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=pack.main(['timemachine','--plan',str(base/'plan.json'),'--calendar',str(base/'calendar.json'),
                               '--offline',str(base/'chart.json'),'--now',now.isoformat(),'--replays','10000'])
            self.assertEqual(code,0)
            result=json.loads(output.getvalue())
            self.assertEqual(result['monte_carlo']['replays'],10000)
            self.assertEqual(len(result['monte_carlo']['sample_paths']),160)
            self.assertEqual(len(result['monte_carlo']['bands'][0]),5)
            self.assertEqual(result['history']['summary']['triggered'],30)

    def test_financial_q4_and_latest_revision(self):
        periods=[]
        for start,end,value in [('2025-04-01','2025-06-30',100),('2025-07-01','2025-09-30',120),
                                ('2025-10-01','2025-12-31',130),('2025-04-01','2026-03-31',500)]:
            periods.append({'start':start,'end':end,'filed_at':'2026-05-01T10:00:00+05:30','source_url':'https://www.nseindia.com/example',
                            'unit':'crore','revenue':value,'pat':value/10})
        periods.append(dict(periods[0],filed_at='2026-05-02T10:00:00+05:30',revenue=110))
        result=financial_analysis({'symbol':'TEST.NS','scope':'consolidated','periods':periods})
        q4=result['periods'][-1]
        self.assertTrue(q4['derived_q4'])
        self.assertEqual(q4['metrics_inr_except_eps']['revenue'],'1400000000')


if __name__=='__main__': unittest.main()

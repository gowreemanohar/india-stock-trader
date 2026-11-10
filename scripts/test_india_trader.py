"""Offline behavioral checks using synthetic data; no user data or network."""
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import india_trader as it
from chart_rules import rsi


def fixture(interval='5m', symbol='RELIANCE.NS', currency='INR'):
    start = it.now_ist('2026-10-30T09:15:00+05:30')
    closes = [100, 101, 100, 103, 102]
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': symbol, 'currency': currency, 'instrumentType': 'EQUITY', 'dataGranularity': interval},
        'timestamp': [(start + it.FIVE * i).timestamp() for i in range(len(closes))],
        'indicators': {'quote': [{'open': closes, 'high': [x + 1 for x in closes],
                                  'low': [x - 1 for x in closes], 'close': closes, 'volume': [1000] * len(closes)}]}}]}}


class IndianTraderTests(unittest.TestCase):
    def test_symbol_boundaries(self):
        self.assertEqual(it.symbols('reliance.ns,500325.bo,RELIANCE.NS'), ['RELIANCE.NS', '500325.BO'])
        for value in ('AAPL', '../../x.NS', 'RELIANCE.NS?token=x', '^NSEI', ''):
            with self.assertRaises(ValueError):
                it.symbols(value)

    def test_ist_conversion(self):
        self.assertEqual(it.now_ist('2026-10-30T03:45:00Z').hour, 9)
        self.assertEqual(it.now_ist('2026-10-30T09:15').utcoffset(), dt.timedelta(hours=5, minutes=30))

    def test_currency_symbol_and_interval_validation(self):
        for doc in (fixture(currency='USD'), fixture(symbol='TCS.NS'), fixture(interval='1d')):
            with self.assertRaises(ValueError):
                it.parse_chart(doc, 'RELIANCE.NS', '5m')

    def test_orb_completed_bars_only(self):
        _, bars = it.parse_chart(fixture(), 'RELIANCE.NS', '5m')
        args = ('2026-10-30', '09:15', '15:15', 15)
        with self.assertRaises(ValueError):
            it.orb(bars, it.now_ist('2026-10-30T09:34:59'), *args)
        result = it.orb(bars, it.now_ist('2026-10-30T09:35'), *args)
        self.assertEqual(result['opening_range_high_inr'], 102)
        self.assertEqual(result['first_breakout']['confirmed_at'], '2026-10-30T09:35:00+05:30')
        self.assertEqual(result['complete_bars'], 4)

    def test_missing_or_stale_bars_rejected(self):
        _, bars = it.parse_chart(fixture(), 'RELIANCE.NS', '5m')
        for values, clock in ((bars[1:], '09:40'), (bars, '10:00')):
            with self.assertRaises(ValueError):
                it.orb(values, it.now_ist('2026-10-30T' + clock), '2026-10-30', '09:15', '15:15', 15)

    def test_daily_excludes_today_and_future(self):
        start = it.now_ist('2026-09-01T09:15')
        bars = [{'start': start + dt.timedelta(days=i), 'close': 100 + i, 'volume': 1000} for i in range(35)]
        result = it.daily(bars, start + dt.timedelta(days=31), 0, 0)
        self.assertEqual(result['close_inr'], 130)
        self.assertIn('breakout_20d', result['setups'])
        self.assertEqual(result['age_calendar_days'], 1)

    def test_original_flat_series_rsi(self):
        self.assertEqual(rsi([100] * 35), 100)



    def test_offline_cli_no_network_and_partial_failures(self):
        with tempfile.TemporaryDirectory(prefix='india-stock-trader-test-') as folder:
            path = Path(folder) / 'chart.json'
            path.write_text(json.dumps({'RELIANCE.NS': fixture()}), encoding='utf-8')
            output = io.StringIO()
            with patch.object(it, 'fetch', side_effect=AssertionError('Network forbidden')), contextlib.redirect_stdout(output):
                code = it.main(['orb', '--symbols', 'RELIANCE.NS,TCS.NS', '--offline', str(path), '--now', '2026-10-30T09:35',
                                '--session-date', '2026-10-30', '--session-open', '09:15', '--session-end', '15:15'])
            report = json.loads(output.getvalue())
            self.assertEqual((code, report['succeeded'], report['failed'], report['partial']), (2, 1, 1, True))


if __name__ == '__main__':
    unittest.main()

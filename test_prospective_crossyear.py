"""Boundary tests for prospective source years, stock calendars and causal events."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from prospective_sources import annual_sources, warmup_months, source_cutoff
from prospective_replay import annual_event_document, benchmark_actions, next_entry
from tpex_proxy_features import features
from twse_history.build_history import adjust_prices


def schedule(year, extra=''):
    rows = ''.join(f'<tr><td>休市</td><td>{month}月1日</td></tr>' for month in range(1, 13))
    return json.dumps(dict(stat='ok',endDate=f'{year}0101',data=dict(html=f'<table><tr><td>民國{year-1911}年</td></tr>{rows}{extra}</table>'))).encode()


def pack(raw, spec, doc):
    key='raw/'+spec['key'];raw[key]=json.dumps(doc).encode()
    raw[key+'.meta.json']=json.dumps(dict(url=spec['url'],sha256=hashlib.sha256(raw[key]).hexdigest(),observed_at='2026-10-16T08:00:00+08:00')).encode()


class CrossyearTests(unittest.TestCase):
    def test_sealed_derived_evidence_cannot_be_regenerated(self):
        from prospective_replay import generate, replay
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'journal/signal').mkdir(parents=True)
            (root/'journal/signal/2026-10-15.json').write_text('{}')
            for operation in (generate,replay):
                with self.assertRaisesRegex(ValueError,'Sealed run'):
                    operation(root)

    def test_acquisition_covers_both_years_with_exact_cutoffs(self):
        self.assertEqual(warmup_months('2027-01-15'),['2026-09','2026-10','2026-11','2026-12','2027-01'])
        specs=annual_sources('2026-09-01','2027-01-15')
        self.assertEqual(len(specs),14)
        self.assertEqual({s['year'] for s in specs},{2026,2027})
        for s in specs:
            self.assertEqual(s['cutoff'],'2026-12-31' if s['year']==2026 else '2027-01-15')
        self.assertIn('event_2026_excal.json',{s['key'] for s in specs})
        self.assertIn('event_excal.json',{s['key'] for s in specs})

    def test_missing_prior_year_or_ignored_date_fails(self):
        spec=next(s for s in annual_sources('2025-09-01','2026-01-15') if s['market']=='tpex')
        with self.assertRaisesRegex(ValueError,'Missing annual'):annual_event_document({},spec)
        raw={};pack(raw,spec,dict(stat='ok',date='20260101~20260115',tables=[dict(data=[],fields=[],totalCount=0)]))
        with self.assertRaisesRegex(ValueError,'range differs'):annual_event_document(raw,spec)
        pack(raw,spec,dict(stat='ok',date='20250101~20251231',tables=[dict(data=[['115/01/02','1234','x','100','50']],fields=['除權息日期','代號','名稱','除權息前收盤價','除權息參考價'],totalCount=1)]))
        with self.assertRaisesRegex(ValueError,'outside requested'):annual_event_document(raw,spec)

    def test_empty_event_source_with_unrecognized_schema_is_not_no_events(self):
        spec=next(s for s in annual_sources('2025-09-01','2026-01-15') if s['market']=='tpex')
        raw={};pack(raw,spec,dict(stat='ok',date='20250101~20251231',tables=[dict(fields=[],data=[],totalCount=0)]))
        with self.assertRaisesRegex(ValueError,'schema differs'):annual_event_document(raw,spec)

    def test_new_year_entry_requires_new_year_schedule(self):
        with self.assertRaisesRegex(ValueError,'Next-year'):next_entry(schedule(2026),'2026-12-31')
        self.assertEqual(next_entry(schedule(2026),'2026-12-31',schedule(2027)),'2027-01-04T09:00:00+08:00')
        with self.assertRaises(ValueError):next_entry(schedule(2026),'2026-12-31',schedule(2026))

    def test_stock_settlement_only_days_and_bond_days_differ(self):
        extra='<tr><td>國際債券交易系統最後交易日</td><td>2月10日</td><td>2月11日市場無交易</td></tr><tr><td>股票交易系統最後交易日</td><td>2月11日</td><td>2月12日及2月13日市場無交易</td></tr>'
        self.assertEqual(next_entry(schedule(2026,extra),'2026-02-10'),'2026-02-11T09:00:00+08:00')
        self.assertEqual(next_entry(schedule(2026,extra),'2026-02-11'),'2026-02-16T09:00:00+08:00')

    def test_source_clock_rejects_preclose_backdated_and_naive(self):
        now=dt.datetime(2026,10,16,14,59,tzinfo=ZoneInfo('Asia/Taipei'))
        with self.assertRaises(ValueError):source_cutoff('2026-10-16',now=now)
        with self.assertRaises(ValueError):source_cutoff('2026-10-15',now=now.replace(hour=16))
        with self.assertRaises(ValueError):source_cutoff('2026-10-16',now=now.replace(tzinfo=None))
        source_cutoff('2026-10-16',now=now.replace(hour=15))

    def test_prior_year_price_event_and_unknown_mask_cross_into_january(self):
        days=pd.bdate_range('2025-09-01',periods=100)
        close=np.full(len(days),100.0);close[70:]=50.0
        frame=pd.DataFrame(dict(date=days,code='1234',open=close,high=close,low=close,close=close,volume_shares=1000,primary_pool=True,confirmed_subset=True,type_evidence='confirmed_ordinary'))
        event=dict(event_date=days[70].strftime('%Y-%m-%d'),official_last_close=100,official_reference=50,status='last_close_matches')
        result=features(frame,days,[event])
        self.assertTrue(result.iloc[-1].date.startswith('2026-01'))
        self.assertAlmostEqual(result.iloc[-1].mom60,0)
        event['status']='last_close_mismatch'
        self.assertTrue(pd.isna(features(frame,days,[event]).iloc[-1].mom60))

    def test_benchmark_prior_year_event_uses_one_continuous_scale(self):
        specs=annual_sources('2025-09-01','2026-01-15');raw={}
        fields=dict(exrights=['資料日期','股票代號','股票名稱','除權息前收盤價','除權息參考價','權/息'],reduction=['恢復買賣日期','股票代號','名稱','停止買賣前收盤價格','恢復買賣參考價'],par_change=['恢復買賣日期','股票代號','名稱','停止買賣前收盤價格','恢復買賣參考價'],split=['恢復買賣日期','ETF代號','名稱','停止買賣前收盤價格','恢復買賣參考價'])
        for spec in (s for s in specs if s['market']=='twse'):
            rows=[['114/12/30','0050','ETF','100','50','息']] if spec['year']==2025 and spec['kind']=='exrights' else []
            pack(raw,spec,dict(stat='OK',fields=fields[spec['kind']],data=rows))
        days=pd.DatetimeIndex(['2025-12-29','2025-12-30','2026-01-02'])
        with tempfile.TemporaryDirectory() as d:
            actions=benchmark_actions(raw,specs,Path(d),days,'2026-01-15')
            self.assertEqual(len(actions),1)
            quotes=pd.DataFrame(dict(date=days,symbol='0050',open=[100,50,50],high=[100,50,50],low=[100,50,50],close=[100,50,50]))
            adjusted=adjust_prices(quotes,actions,pd.Timestamp('2026-01-15'))
            np.testing.assert_allclose(adjusted.adj_close,[100,100,100])
            for key in list(raw):
                if key.startswith('raw/benchmark_event_2025_'):del raw[key]
            with self.assertRaisesRegex(ValueError,'Missing annual'):benchmark_actions(raw,specs,Path(d),days,'2026-01-15')

    def test_empty_benchmark_event_year_is_known_empty(self):
        specs=[s for s in annual_sources('2026-06-01','2026-10-15') if s['market']=='twse'];raw={}
        for spec in specs:
            column='資料日期' if spec['kind']=='exrights' else '恢復買賣日期'
            other=['股票代號','股票名稱','除權息前收盤價','除權息參考價'] if spec['kind']=='exrights' else [('ETF代號' if spec['kind']=='split' else '股票代號'),'名稱','停止買賣前收盤價格','恢復買賣參考價']
            pack(raw,spec,dict(stat='OK',fields=[column]+other,data=[]))
        days=pd.DatetimeIndex(['2026-10-14','2026-10-15'])
        with tempfile.TemporaryDirectory() as d:
            actions=benchmark_actions(raw,specs,Path(d),days,'2026-10-15')
            quotes=pd.DataFrame(dict(date=days,symbol='0050',open=100,high=100,low=100,close=100))
            self.assertTrue(actions.empty)
            np.testing.assert_allclose(adjust_prices(quotes,actions,days[-1]).adj_close,[100,100])

if __name__=='__main__':unittest.main()

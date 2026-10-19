"""Replay old ETF targets on a separately frozen share/cash settlement scenario."""
import argparse
import csv
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cash_benchmark import validate_inputs
from research_reassessment import verified_bundle
from research_runtime import atomic_bytes,atomic_json,sha256
from risk_control import metrics
from settled_etf_account import replay
from source_checkpoint import readback

ROOT=Path('inputs/rebalance_accounting_20261020')
OUT=Path('deliverables/rebalance_accounting_20261020')
POLICY=Path('configs/rebalance_accounting_protocol_20261020.json')


def policy():
    p=json.loads(POLICY.read_text())
    if sha256(POLICY)!=json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:raise ValueError('Frozen accounting protocol drift')
    for file,digest in p['inputs'].items():
        if sha256(Path(file))!=digest:raise ValueError('Frozen accounting input drift: '+file)
    for file,digest in p['prior_checkpoints'].items():
        if sha256(Path(file))!=digest:raise ValueError('Prior checkpoint drift')
        for name,h in json.loads(Path(file).read_text())['files'].items():
            if sha256(Path(name))!=h:raise ValueError('Prior frozen file drift: '+name)
    return p


def verify():
    p=policy();pkg,transfer=readback(Path('deliverables/benchmark_cash_20261019'),'sources')
    manifest=verified_bundle(p['source_price_archive'],p['source_price_archive_sha256'])
    source=json.loads(Path('deliverables/benchmark_cash_20261019/source_ledger.json').read_text())
    frame=pd.read_csv('inputs/benchmark_cash_20261019/market.csv.gz')
    if sha256(Path('inputs/benchmark_cash_20261019/market.csv.gz'))!=source['extracted_market_sha256']:raise ValueError('Verified market extract differs')
    validate_inputs(frame,source['distributions'],source['split'],p['start'],p['end'],1000)
    old=pd.read_csv('inputs/risk_control_20261018/market.csv.gz');joined=frame.merge(old,on='date',suffixes=('_new','_old'),validate='one_to_one')
    if len(joined)!=len(frame) or any(not np.allclose(joined[key+'_new'],joined[key+'_old'],equal_nan=True,atol=1e-9,rtol=1e-12) for key in ['open','close']):
        raise ValueError('Old target price calendar or raw quotes differ from cash source')
    atomic_json(OUT/'source_receipt.json',dict(status='passed_for_declared_accounting_replay',prior_files_hash_verified=True,
        price_archive_sha256=p['source_price_archive_sha256'],price_manifest_files=len(manifest),raw_action_archive_sha256=pkg['sha256'],raw_action_manifest_files=pkg['manifest_files'],
        roundtrip_verified=transfer['roundtrip_verified'],sha_crc_manifest_verified=True,calendar_and_raw_quotes_matched=len(frame),
        new_downloads=0,raw_retransmissions=0,historical_pit_verified=False,source_start=frame.date.min(),source_end=frame.date.max()))


def run():
    p=policy();receipt=json.loads((OUT/'source_receipt.json').read_text())
    if not receipt['sha_crc_manifest_verified']:raise ValueError('Verified saved sources required')
    source=json.loads(Path('deliverables/benchmark_cash_20261019/source_ledger.json').read_text())
    with gzip.open('inputs/benchmark_cash_20261019/market.csv.gz','rt') as f:market=list(csv.DictReader(f))
    with gzip.open('deliverables/risk_control_20261018/daily.csv.gz','rt') as f:targets=list(csv.DictReader(f))
    saved=[];summary=[];trade_rows=[]
    for cost in p['cost_rates']:
        for method in p['methods']:
            decisions=[r for r in targets if r['method']==method and Decimal(r['cost_rate'])==Decimal(cost) and p['start']<=r['date']<=p['end']]
            result=replay(market,decisions,source['distributions'],source['split'],p['start'],p['end'],p['initial_cash_twd'],cost)
            saved.append(dict(method=method,cost=cost,**result))
            daily=[r for r in result['daily'] if r['market_session']];nav=np.array([float(r['wealth'])/float(p['initial_cash_twd']) for r in daily])
            returns=nav/np.r_[1.,nav[:-1]]-1
            report=pd.DataFrame(dict(nav=nav,daily_return=returns,traded=0.,charge=0.,exposure=[float(r['units'])*float(r['raw_close'])/float(r['wealth']) for r in daily],carried_valuation=[r['carried_market_valuation'] for r in daily]))
            stats=metrics(report);yearly=[]
            for year in ['2024','2025']:
                indexes=[i for i,r in enumerate(daily) if r['date'].startswith(year)]
                yearly.append(dict(year=year,account_scenario_return=float(nav[indexes[-1]]/(nav[indexes[0]-1] if indexes[0] else 1)-1)))
            last=result['daily'][-1];proxy_end=Decimal(decisions[-1]['nav']);change=Decimal(last['wealth'])/Decimal(p['initial_cash_twd'])-1
            summary.append(dict(method=method,cost_rate=cost,market_days=len(daily),calendar_days=len(result['daily']),
                account_scenario_change=str(change),old_proxy_same_period_change=str(proxy_end-1),account_minus_proxy_pp=str((change-(proxy_end-1))*100),
                ending_wealth_twd=last['wealth'],ending_units=last['units'],ending_bank_cash_twd=last['bank_cash'],ending_dividend_receivable_twd=last['dividend_receivable'],ending_sale_receivable_twd=last['sale_receivable'],ending_purchase_payable_twd=last['purchase_payable'],
                target_attempts=len(result['trades']),filled_quote_scenarios=sum(t['status']=='filled_quote_scenario' for t in result['trades']),rejections=sum(t['status'].startswith('rejected') for t in result['trades']),
                minimum_spendable_cash_twd=str(min(Decimal(r['spendable_cash']) for r in result['daily'])),total_hypothetical_cost_twd=str(sum((Decimal(t['cost']) for t in result['trades']),Decimal(0))),
                maximum_close_drawdown=stats['max_drawdown'],annualized_daily_vol=stats['annualized_vol'],carried_market_valuations=stats['missing_valuations'],calendar_subperiods=yearly,
                scheduled_missing_vol_days=[r['date'] for r in decisions if r['reason']=='missing_vol_window']))
            trade_rows += [dict(method=method,cost_rate=cost,**r) for r in result['trades']]
    comparisons=[]
    for cost in p['cost_rates']:
        dynamic,static=[next(s for s in summary if s['method']==method and s['cost_rate']==cost) for method in ['dynamic','calibration_static']]
        comparisons.append(dict(cost_rate=cost,account_dynamic_minus_static_pp=str((Decimal(dynamic['account_scenario_change'])-Decimal(static['account_scenario_change']))*100),
            yearly_dynamic_minus_static_pp=[dict(year=a['year'],difference_pp=100*(a['account_scenario_return']-b['account_scenario_return'])) for a,b in zip(dynamic['calendar_subperiods'],static['calendar_subperiods'])]))
    ROOT.mkdir(parents=True,exist_ok=True)
    atomic_bytes(ROOT/'accounts.json.gz',gzip.compress(json.dumps(saved,separators=(',',':')).encode(),mtime=0))
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(trade_rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(trade_rows)
    atomic_bytes(OUT/'trade_scenarios.csv',stream.getvalue().encode())
    atomic_json(OUT/'summary.json',dict(status='accounting_scenario_computed_see_acceptance_receipt',cases=summary,paired_account_comparisons=comparisons,
        bulk_accounts_sha256=sha256(ROOT/'accounts.json.gz'),targets_unchanged=True,old_research_gate_retested=False,old_research_failed_gate_preserved=True,
        fractional_shares=True,actual_fills_verified=False,historical_pit_verified=False,profit_edge_proven=False,valid_prospective_signal_date=None))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['verify','run']);globals()[parser.parse_args().stage]()

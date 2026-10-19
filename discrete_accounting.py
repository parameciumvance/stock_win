"""Fixed 1/1000 share-grid implementation scenarios, with exact old fractional controls."""
import argparse
import csv
from decimal import Decimal as D
from fractions import Fraction as F
import gzip
import io
import json
from pathlib import Path

from discrete_etf_account import replay_grid
from research_reassessment import verified_bundle
from research_runtime import atomic_bytes,atomic_json,sha256
from source_checkpoint import readback

ROOT=Path('inputs/discrete_accounting_20261020')
OUT=Path('deliverables/discrete_accounting_20261020')
POLICY=Path('configs/discrete_accounting_protocol_20261020.json')


def policy():
    p=json.loads(POLICY.read_text())
    if sha256(POLICY)!=json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:raise ValueError('Frozen discrete accounting protocol drift')
    for file,digest in p['inputs'].items():
        if sha256(Path(file))!=digest:raise ValueError('Frozen input drift: '+file)
    for file,digest in p['prior_checkpoints'].items():
        if sha256(Path(file))!=digest:raise ValueError('Prior checkpoint drift')
        for name,h in json.loads(Path(file).read_text())['files'].items():
            if sha256(Path(name))!=h:raise ValueError('Prior frozen artifact drift: '+name)
    return p


def verify():
    p=policy();package,backup=readback(Path('deliverables/benchmark_cash_20261019'),'sources')
    manifest=verified_bundle(p['source_price_archive'],p['source_price_archive_sha256'])
    accepted=json.loads(Path('deliverables/rebalance_accounting_20261020/acceptance.json').read_text())
    if not accepted['accounting_gate_passed'] or accepted['accounts_sha256']!=sha256(Path('inputs/rebalance_accounting_20261020/accounts.json.gz')):
        raise ValueError('Fractional baseline not independently accepted')
    atomic_json(OUT/'source_receipt.json',dict(status='passed_saved_inputs_only',prior_frozen_files_verified=True,
        price_archive_sha256=p['source_price_archive_sha256'],price_manifest_files=len(manifest),raw_action_archive_sha256=package['sha256'],raw_action_manifest_files=package['manifest_files'],
        roundtrip_verified=backup['roundtrip_verified'],crc_manifest_verified=True,new_raw_downloads=0,raw_retransmissions=0))


def average(values):return sum(values,D(0))/len(values) if values else D(0)


def run():
    p=policy();receipt=json.loads((OUT/'source_receipt.json').read_text())
    if not receipt['crc_manifest_verified']:raise ValueError('Verified raw inputs required')
    source=json.loads(Path('deliverables/benchmark_cash_20261019/source_ledger.json').read_text())
    with gzip.open('inputs/benchmark_cash_20261019/market.csv.gz','rt') as f:market=list(csv.DictReader(f))
    with gzip.open('deliverables/risk_control_20261018/daily.csv.gz','rt') as f:targets=list(csv.DictReader(f))
    with gzip.open('inputs/rebalance_accounting_20261020/accounts.json.gz','rt') as f:old=json.load(f)
    cases=[];summaries=[];trade_rows=[];controls=0
    for mode in p['quantity_modes']:
        for cost in p['cost_rates']:
            for method in p['methods']:
                decisions=[r for r in targets if r['method']==method and D(r['cost_rate'])==D(cost) and p['start']<=r['date']<=p['end']]
                replay=replay_grid(market,decisions,source['distributions'],source['split'],p['start'],p['end'],p['initial_cash_twd'],cost,mode['unit'])
                if mode['unit'] is None:
                    baseline=next(x for x in old if x['method']==method and D(x['cost'])==D(cost))
                    if replay!={k:baseline[k] for k in ['daily','trades','claims']}:raise ValueError('Fractional control differs from frozen prior replay')
                    controls+=1
                case=dict(mode=mode['name'],unit=mode['unit'],method=method,cost=cost,**replay);cases.append(case)
                daily=[r for r in replay['daily'] if r['market_session']];bydate={r['date']:r for r in daily};shortfalls=[]
                for trade in replay['trades']:
                    row=bydate[trade['date']];postnav=D(trade['nav_before'])-D(trade['cost'])
                    achieved=D(row['units'])*D(trade['price'])/postnav
                    shortfall=(D(trade['target'])-achieved)*100
                    if shortfall < D('-1e-20'):raise ValueError('Quantized trade exceeded target')
                    shortfalls.append(max(D(0),shortfall))
                    trade_rows.append(dict(mode=mode['name'],unit='' if mode['unit'] is None else mode['unit'],method=method,cost_rate=cost,
                        date=trade['date'],due=trade['due'],target=trade['target'],achieved_weight=str(achieved),shortfall_pp=str(max(D(0),shortfall)),
                        shares_delta=trade['shares_delta'],hypothetical_cost_twd=trade['cost'],status=trade['status']))
                last=daily[-1];change=D(last['wealth'])/D(p['initial_cash_twd'])-1
                summaries.append(dict(mode=mode['name'],unit=mode['unit'],method=method,cost_rate=cost,market_days=len(daily),calendar_days=len(replay['daily']),
                    account_scenario_change=str(change),ending_units=last['units'],ending_wealth_twd=last['wealth'],ending_bank_cash_twd=last['bank_cash'],
                    ending_dividend_receivable_twd=last['dividend_receivable'],ending_sale_receivable_twd=last['sale_receivable'],ending_purchase_payable_twd=last['purchase_payable'],
                    mean_spendable_cash_fraction=str(average([D(r['spendable_cash'])/D(r['wealth']) for r in daily])),
                    mean_equity_exposure=str(average([D(r['units'])*D(r['raw_close'])/D(r['wealth']) for r in daily])),
                    mean_target_shortfall_pp=str(average(shortfalls)),max_target_shortfall_pp=str(max(shortfalls,default=D(0))),
                    filled_quote_scenarios=sum(t['status']=='filled_quote_scenario' for t in replay['trades']),
                    rounding_no_change=sum(t['status']=='rounded_no_change' for t in replay['trades']),rejections=sum(t['status'].startswith('rejected') for t in replay['trades']),
                    hypothetical_cost_twd=str(sum((D(t['cost']) for t in replay['trades']),D(0))),carried_market_valuations=sum(r['carried_market_valuation'] for r in daily)))
    for row in summaries:
        control=next(r for r in summaries if r['mode']=='fractional' and r['method']==row['method'] and r['cost_rate']==row['cost_rate'])
        row['minus_fractional_pp']=str((D(row['account_scenario_change'])-D(control['account_scenario_change']))*100)
    ROOT.mkdir(parents=True,exist_ok=True)
    atomic_bytes(ROOT/'accounts.json.gz',gzip.compress(json.dumps(cases,separators=(',',':')).encode(),mtime=0))
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(trade_rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(trade_rows)
    atomic_bytes(OUT/'trade_scenarios.csv',stream.getvalue().encode())
    atomic_json(OUT/'summary.json',dict(status='discrete_quote_scenarios_computed_see_acceptance_receipt',cases=summaries,fractional_controls_exactly_matched=controls,
        bulk_accounts_sha256=sha256(ROOT/'accounts.json.gz'),quantity_modes_selected_as_strategy=False,old_risk_gate_changed=False,
        actual_boardlot_fills_verified=False,actual_oddlot_fills_verified=False,broker_minimum_fees_verified=False,profit_edge_proven=False,valid_prospective_signal_date=None))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['verify','run']);globals()[parser.parse_args().stage]()

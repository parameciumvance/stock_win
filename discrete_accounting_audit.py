"""Independent share-grid inequalities and direct cash-flow reconstruction."""
import csv
from datetime import date,timedelta
from decimal import Decimal as D,localcontext
from fractions import Fraction as F
import gzip
import json
from pathlib import Path

from research_runtime import atomic_json,sha256


def audit():
    root=Path('inputs/discrete_accounting_20261020');out=Path('deliverables/discrete_accounting_20261020')
    protocol=Path('configs/discrete_accounting_protocol_20261020.json');p=json.loads(protocol.read_text())
    assert sha256(protocol)==json.loads((out/'protocol_freeze.json').read_text())['protocol_sha256']
    assert all(sha256(Path(file))==digest for file,digest in p['inputs'].items())
    with gzip.open(root/'accounts.json.gz','rt') as f:accounts=json.load(f)
    with gzip.open('inputs/rebalance_accounting_20261020/accounts.json.gz','rt') as f:old=json.load(f)
    with gzip.open('inputs/benchmark_cash_20261019/market.csv.gz','rt') as f:market=list(csv.DictReader(f))
    with gzip.open('deliverables/risk_control_20261018/daily.csv.gz','rt') as f:decisions=list(csv.DictReader(f))
    source=json.loads(Path('deliverables/benchmark_cash_20261019/source_ledger.json').read_text());summary=json.loads((out/'summary.json').read_text())
    assert sha256(root/'accounts.json.gz')==summary['bulk_accounts_sha256']
    calendar=[r['date'] for r in market];quotes={r['date']:r for r in market};events={r['ex_date']:r for r in source['distributions']}
    expected={(m['name'],c,method) for m in p['quantity_modes'] for c in p['cost_rates'] for method in p['methods']}
    assert {(a['mode'],a['cost'],a['method']) for a in accounts}==expected and len(accounts)==len(expected)
    max_error=F(0);eps=F(1,10**18);checked=0;attempts=0;controls=0;integer_rows=0
    def compare(observed,value):
        nonlocal max_error
        error=abs(F(str(observed))-value);max_error=max(max_error,error);assert error<=eps,(str(observed),str(value))
    with localcontext() as context:
        context.prec=50
        dec=lambda f:D(f.numerator)/D(f.denominator)
        for a in accounts:
            method,cost,unit=a['method'],F(a['cost']),a['unit'];cash=F(p['initial_cash_twd']);units=F(0);buys=[];sales=[];claims=[];lastprice=None;lastquoted=None
            if unit is None:
                baseline=next(b for b in old if b['method']==method and F(b['cost'])==cost)
                assert {k:a[k] for k in ['daily','trades','claims']}=={k:baseline[k] for k in ['daily','trades','claims']};controls+=1
            else:assert type(unit)is int and unit in [1,1000]
            total=lambda items:sum((v for day,v in items),F(0))
            targets={r['date']:r for r in decisions if r['method']==method and F(r['cost_rate'])==cost and p['start']<=r['date']<=p['end']}
            trades={t['date']:t for t in a['trades']};assert len(trades)==len(a['trades'])
            assert set(trades)=={d for d,t in targets.items() if t['target'] not in ['',None,'nan','NaN']}
            idle=[];exposures=[];shortfalls=[]
            for offset,saved in enumerate(a['daily']):
                day=(date.fromisoformat(p['start'])+timedelta(days=offset)).isoformat();assert saved['date']==day
                settled_buy=sum((v for d,v in buys if d==day),F(0));settled_sale=sum((v for d,v in sales if d==day),F(0))
                cash+=settled_sale-settled_buy;buys=[x for x in buys if x[0]!=day];sales=[x for x in sales if x[0]!=day]
                if day==source['split']['date']:
                    units*=F(source['split']['ratio'])
                    if lastprice is not None:lastprice/=F(source['split']['ratio'])
                newclaim=F(0)
                if day in events:
                    e=events[day];newclaim=units*F(str(e['cash_per_unit']));claims.append((e['payment_date'],newclaim))
                    claim=next(c for c in a['claims'] if c['ex_date']==day);compare(claim['amount'],newclaim);compare(claim['entitled_units'],units)
                quote=quotes.get(day);quoted=quote is not None and quote['close'] not in ['',None,'nan','NaN']
                if day in trades:
                    t=trades[day];target=F(targets[day]['target']);price=F(quote['open']);old_units=units
                    wealth=units*price+cash+total(sales)+total(claims)-total(buys);available=cash-total(buys)
                    assert t['due']==calendar[calendar.index(day)+2] and F(t['target'])==target
                    compare(t['nav_before'],wealth);compare(t['spendable_before'],available)
                    if unit is not None:
                        chosen=F(t['rounded_final_shares']);ideal=F(t['ideal_final_shares_exact'])
                        assert chosen.denominator==1 and chosen%unit==0 and chosen<=ideal<chosen+unit
                        # Prove maximal grid holding by post-cost inequalities, not production's floor formula.
                        value=(chosen-units)*price;fee=abs(value)*cost
                        assert chosen*price<=target*(wealth-fee)+eps
                        nxt=chosen+unit;nextfee=abs((nxt-units)*price)*cost
                        assert nxt*price>target*(wealth-nextfee)-eps
                        compare(ideal*price,target*(wealth-abs((ideal-units)*price)*cost))
                        if t['status'].startswith('rejected'):
                            assert value>0 and value+fee>available;assert F(t['shares_delta'])==0
                        else:assert F(t['shares_delta'])==chosen-units
                    if not t['status'].startswith('rejected'):
                        quantity=F(t['shares_delta']);value=quantity*price;fee=abs(value)*cost
                        compare(t['delta'],value);compare(t['cost'],fee)
                        if quantity>0:
                            assert value+fee<=available+eps;buys.append((t['due'],value+fee))
                        elif quantity<0:sales.append((t['due'],-value-fee))
                        units+=quantity
                        if unit is None:compare(units*price,target*(wealth-fee))
                    else:assert F(t['cost'])==0
                    postnav=wealth-F(t['cost']);gap=target-units*price/postnav;assert gap>=-eps
                    shortfalls.append(max(D(0),dec(gap)*100));attempts+=1
                if quoted:lastprice=F(quote['close']);lastquoted=day
                paid=sum((v for d,v in claims if d==day),F(0));cash+=paid;claims=[x for x in claims if x[0]!=day]
                assert cash>=-eps and cash-total(buys)>=-eps and units>=-eps
                if unit is not None:assert units.denominator==1 and units%unit==0;integer_rows+=1
                values=dict(units=units,raw_close=lastprice,bank_cash=cash,purchase_payable=total(buys),sale_receivable=total(sales),dividend_receivable=total(claims),
                    spendable_cash=cash-total(buys),wealth=units*lastprice+cash+total(sales)+total(claims)-total(buys),paid_dividend=paid,new_claim=newclaim,settled_buy=settled_buy,settled_sale=settled_sale)
                for key,value in values.items():compare(saved[key],value)
                assert saved['last_quote_date']==lastquoted and saved['market_session']==(day in targets)
                assert saved['carried_market_valuation']==(day in targets and not quoted)
                if day in targets:
                    idle.append(dec(values['spendable_cash']/values['wealth']));exposures.append(dec(units*lastprice/values['wealth']))
                checked+=1
            assert saved['date']==p['end']
            s=next(s for s in summary['cases'] if s['mode']==a['mode'] and s['method']==method and F(s['cost_rate'])==cost)
            compare(s['account_scenario_change'],values['wealth']/F(p['initial_cash_twd'])-1)
            for key,value in [('mean_spendable_cash_fraction',sum(idle)/len(idle)),('mean_equity_exposure',sum(exposures)/len(exposures)),('mean_target_shortfall_pp',sum(shortfalls)/len(shortfalls)),('max_target_shortfall_pp',max(shortfalls))]:compare(s[key],F(value))
            assert s['rounding_no_change']==sum(t['status']=='rounded_no_change' for t in a['trades'])
    atomic_json(out/'independent_audit.json',dict(status='passed',cases=len(accounts),calendar_account_rows_verified=checked,integer_grid_account_rows_verified=integer_rows,
        target_attempts_verified=attempts,fractional_controls_exactly_matched=controls,maximum_absolute_field_error=str(float(max_error)),absolute_field_tolerance='1e-18',
        method='Fraction date-flow accounting and maximal-grid inequalities; Decimal50independentcash/exposure/shortfallmeans; no production Accountorroundingsolver'))
    atomic_json(out/'acceptance.json',dict(accounting_and_quantity_gates_passed=True,summary_sha256=sha256(out/'summary.json'),accounts_sha256=sha256(root/'accounts.json.gz'),
        independent_audit_sha256=sha256(out/'independent_audit.json'),actual_fills_verified=False,broker_minimum_fees_verified=False,profit_edge_proven=False,valid_prospective_signal_date=None))


if __name__=='__main__':audit()

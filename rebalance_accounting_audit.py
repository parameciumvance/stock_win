"""Independent exact-rational ledger audit, using no production Account/replay methods."""
import csv
from datetime import date,timedelta
from fractions import Fraction as F
import gzip
import json
from pathlib import Path

from research_runtime import atomic_json,sha256


def audit():
    root=Path('inputs/rebalance_accounting_20261020');out=Path('deliverables/rebalance_accounting_20261020')
    p=json.loads(Path('configs/rebalance_accounting_protocol_20261020.json').read_text())
    assert sha256(Path('configs/rebalance_accounting_protocol_20261020.json'))==json.loads((out/'protocol_freeze.json').read_text())['protocol_sha256']
    assert all(sha256(Path(file))==digest for file,digest in p['inputs'].items())
    with gzip.open(root/'accounts.json.gz','rt') as f:accounts=json.load(f)
    summary=json.loads((out/'summary.json').read_text());assert sha256(root/'accounts.json.gz')==summary['bulk_accounts_sha256']
    source=json.loads(Path('deliverables/benchmark_cash_20261019/source_ledger.json').read_text())
    with gzip.open('inputs/benchmark_cash_20261019/market.csv.gz','rt') as f:market=list(csv.DictReader(f))
    with gzip.open('deliverables/risk_control_20261018/daily.csv.gz','rt') as f:decisions=list(csv.DictReader(f))
    calendar=[r['date'] for r in market];quotes={r['date']:r for r in market};events={r['ex_date']:r for r in source['distributions']}
    assert len(accounts)==len(p['cost_rates'])*len(p['methods'])
    checked=0;trade_checks=0;maximum=F(0);eps=F(1,10**18);checks=[]
    def compare(observed,expected):
        nonlocal maximum
        error=abs(F(str(observed))-expected);maximum=max(maximum,error)
        assert error<=eps,(str(observed),str(expected),float(error))
    for account in accounts:
        cost=F(account['cost']);method=account['method'];cash=F(p['initial_cash_twd']);units=F(0);buys=[];sales=[];claims=[];lastprice=None;lastquoted=None
        total=lambda items:sum((v for d,v in items),F(0))
        old=[r for r in decisions if r['method']==method and F(r['cost_rate'])==cost and p['start']<=r['date']<=p['end']]
        targets={r['date']:r for r in old};trades={t['date']:t for t in account['trades']}
        assert len(trades)==len(account['trades'])
        assert set(trades)=={r['date'] for r in old if r['target'] not in ['',None,'nan','NaN']}
        for offset,saved in enumerate(account['daily']):
            day=(date.fromisoformat(p['start'])+timedelta(days=offset)).isoformat();assert day==saved['date']
            settled_buy=sum((v for d,v in buys if d==day),F(0));settled_sale=sum((v for d,v in sales if d==day),F(0))
            cash+=settled_sale-settled_buy;buys=[x for x in buys if x[0]!=day];sales=[x for x in sales if x[0]!=day]
            if day==source['split']['date']:
                units*=F(source['split']['ratio'])
                if lastprice is not None:lastprice/=F(source['split']['ratio'])
            newclaim=F(0)
            if day in events:
                event=events[day];newclaim=units*F(str(event['cash_per_unit']));claims.append((event['payment_date'],newclaim))
                original=next(c for c in account['claims'] if c['ex_date']==day)
                compare(original['entitled_units'],units);compare(original['amount'],newclaim)
            quote=quotes.get(day);quoted=quote is not None and quote['close'] not in ['',None,'nan','NaN']
            if day in trades:
                t=trades[day];target=F(targets[day]['target']);price=F(quote['open'])
                assert t['due']==calendar[calendar.index(day)+2];assert F(t['target'])==target
                asset=units*price;wealth=asset+cash+total(sales)+total(claims)-total(buys);available=cash-total(buys)
                compare(t['nav_before'],wealth);compare(t['spendable_before'],available)
                if t['status'].startswith('rejected'):
                    # Maximum affordable purchase uses all available cash. No production target-delta formula.
                    value=available/(1+cost);maximum_asset=asset+value;maximum_wealth=wealth-value*cost
                    assert maximum_asset+eps<target*maximum_wealth
                    assert F(t['shares_delta'])==0 and F(t['cost'])==0
                else:
                    quantity=F(t['shares_delta']);value=quantity*price;fee=abs(value)*cost
                    compare(t['cost'],fee);compare(t['delta'],value)
                    assert units+quantity>=-eps
                    if quantity>0:
                        assert value+fee<=available+eps;buys.append((t['due'],value+fee))
                    elif quantity<0:sales.append((t['due'],-value-fee))
                    units+=quantity;compare(units*price,target*(wealth-fee))
                trade_checks+=1
            if quoted:lastprice=F(quote['close']);lastquoted=day
            paid=sum((v for d,v in claims if d==day),F(0));cash+=paid;claims=[x for x in claims if x[0]!=day]
            assert cash>=-eps and cash-total(buys)>=-eps
            expected=dict(units=units,raw_close=lastprice,bank_cash=cash,purchase_payable=total(buys),sale_receivable=total(sales),dividend_receivable=total(claims),
                spendable_cash=cash-total(buys),wealth=units*lastprice+cash+total(sales)+total(claims)-total(buys),paid_dividend=paid,new_claim=newclaim,settled_buy=settled_buy,settled_sale=settled_sale)
            for key,value in expected.items():compare(saved[key],value)
            assert saved['last_quote_date']==lastquoted
            assert saved['market_session']==(day in targets)
            assert saved['carried_market_valuation']==(day in targets and not quoted)
            checked+=1
        assert account['daily'][-1]['date']==p['end']
        s=next(s for s in summary['cases'] if s['method']==method and F(s['cost_rate'])==cost)
        compare(s['ending_wealth_twd'],expected['wealth']);compare(s['account_scenario_change'],expected['wealth']/F(p['initial_cash_twd'])-1)
        checks.append(dict(method=method,cost=account['cost'],daily_rows=len(account['daily']),target_attempts=len(trades),passed=True))
    assert len({(a['method'],a['cost']) for a in accounts})==len(accounts)
    atomic_json(out/'independent_audit.json',dict(status='passed',calendar_account_rows_verified=checked,target_attempts_verified=trade_checks,
        maximum_field_absolute_error=str(float(maximum)),absolute_field_tolerance='1e-18',checks=checks,
        method='Exact Fraction direct date-flow reconstruction and post-cost target identity; no production ledger methods or target-delta formula'))
    atomic_json(out/'acceptance.json',dict(accounting_gate_passed=True,summary_sha256=sha256(out/'summary.json'),accounts_sha256=sha256(root/'accounts.json.gz'),
        independent_audit_sha256=sha256(out/'independent_audit.json'),scope='Declared fractional-share,quote/cost/settlement accounting scenario only',
        actual_fills_verified=False,old_resource_gate_retested=False,profit_edge_proven=False,valid_prospective_signal_date=None))


if __name__=='__main__':audit()

"""Independent integer/Fraction checks; analytical worst-cash bound without mask enumeration."""
import csv
from fractions import Fraction as F
import gzip
import json
from pathlib import Path

from research_runtime import atomic_json, sha256


def audit():
    out=Path('deliverables/ipo_account_20261020')
    policy=json.loads(Path('configs/ipo_account_protocol_20261020.json').read_text())
    rows=sorted([r for r in json.loads(Path('deliverables/ipo_screen_20261019/matched_cases.json').read_text()) if r['eligible_for_calculation']],key=lambda r:(r['application_end'],r['symbol']))
    summary=json.loads((out/'summary.json').read_text())
    terms=json.loads((out/'calendar_and_terms.json').read_text())
    with gzip.open('inputs/benchmark_cash_20261019/market.csv.gz','rt') as source:
        calendar=[r['date'] for r in csv.DictReader(source)]
    pathsfile=Path('inputs/ipo_account_20261020/paths.json.gz')
    assert sha256(pathsfile)==summary['paths_sha256']
    with gzip.open(pathsfile,'rt') as source: bulk=json.load(source)
    old=json.loads(Path('deliverables/ipo_screen_20261019/summary.json').read_text())
    a=F(policy['application_fee_twd']);w=F(policy['winner_fee_twd']);checks=[]
    for saved,result in zip(bulk,summary['scenarios'],strict=True):
        assert saved['sale_drag']==result['sale_drag']
        d=F(saved['sale_drag']);units=int(saved['units']);den=int(saved['denominator'])
        principals=[F(r['terms']['offer_price'])*F(r['terms']['lot_size']) for r in rows]
        proceeds=[F(r['raw_listing_quote']['open'])*F(r['terms']['lot_size'])*(1-d) for r in rows]
        probs=[min(F(1),F(r['reported_fields']['實際承銷股數'].replace(',',''))/F(r['reported_fields']['申購股數'].replace(',',''))/F(r['reported_fields']['總合格件'].replace(',',''))) for r in rows]
        # For each date-phase prefix, the cumulative cash is base + sum(bit_i * coefficient_i).
        # Its minimum across ALL masks is base + sum(min(0,coefficient_i)); no probability assumptions needed.
        events=[]
        for i,(r,t) in enumerate(zip(rows,terms['cases'],strict=True)):
            assert r['symbol']==t['symbol']
            assert t['refund_date']==calendar[calendar.index(r['draw_date'])+1]
            assert t['sale_cash_date']==calendar[calendar.index(r['listing_date'])+2]
            events += [(r['application_end'],0,i,-principals[i]-a-w,F(0)),
                       (t['refund_date'],1,i,principals[i]+w,-principals[i]-w),
                       (t['sale_cash_date'],1,i,F(0),proceeds[i])]
        base=F(0);coefficients=[F(0)]*len(rows);mincash=F(0)
        for _,_,i,b,c in sorted(events):
            base+=b;coefficients[i]+=c
            mincash=min(mincash,base+sum(min(F(0),x) for x in coefficients))
        assert abs(F(result['maximum_required_initial_cash_twd'])+mincash)<F(1,10**25)
        assert base==-a*len(rows)
        assert coefficients==[sale-principal-w for sale,principal in zip(proceeds,principals)]
        totalweight=0;weighted=0;lossweight=0;max_required=0
        expected_weight=[];expected_payoff=[]
        for mask,ws,cs,rs in saved['paths']:
            assert mask==len(expected_weight)
            weight=int(ws);cash=int(cs);required=int(rs)
            # Direct product reconstruction and branch payoff, separate from production recursion.
            weight_reference=1;payoff=-a*len(rows)
            for i,p in enumerate(probs):
                win=bool(mask&(1<<i))
                weight_reference*=p.numerator if win else p.denominator-p.numerator
                if win:payoff+=proceeds[i]-principals[i]-w
            assert weight_reference==weight and payoff*units==cash
            totalweight+=weight;weighted+=weight*cash;lossweight+=weight if cash<0 else 0;max_required=max(max_required,required)
            expected_weight.append(weight);expected_payoff.append(cash)
        assert totalweight==den and len(expected_weight)==65536
        assert F(max_required,units)==-mincash
        marginal=-a*len(rows)+sum((p*(sale-principal-w) for p,sale,principal in zip(probs,proceeds,principals)),F(0))
        assert F(weighted,den*units)==marginal
        assert abs(F(result['expected_twd'])-marginal)<F(1,10**25)
        previous=next(s for s in old['scenarios'] if s['sale_drag']==saved['sale_drag'])
        assert abs(F(previous['sum_expected_twd'])-marginal)<F(1,10**20)
        assert abs(F(result['loss_probability'])-F(lossweight,den))<F(1,10**35)
        ordered=sorted(zip(expected_payoff,expected_weight))
        positive=[cash for cash,weight in ordered if weight]
        assert F(result['worst_twd'])==F(positive[0],units)
        assert F(result['best_twd'])==F(positive[-1],units)
        for q,quoted in result['quantiles_twd'].items():
            threshold=F(q)*den;running=0;reference=None
            for cash,weight in ordered:
                running+=weight
                if running and running>=threshold:
                    reference=F(cash,units);break
            assert reference==F(quoted)
        assert abs(F(result['no_win_probability'])-F(expected_weight[0],den))<F(1,10**35)
        assert result['funding_scenario_all_states_pass']==(-mincash<=F(policy['budget_twd']))
        checks.append(dict(sale_drag=saved['sale_drag'],all_mask_weights_and_payoffs_verified=65536,probability_mass_exact=True,
                           mean_matches_old_marginal_screen=True,independent_analytic_cash_bound_verified=True,
                           maximum_required_exact=str(-mincash)))
    atomic_json(out/'independent_audit.json',dict(status='passed',checks=checks,scope='Arithmetic and declared cash scenario; not independence, PIT, actual fills or bank timing proof'))


if __name__=='__main__':audit()

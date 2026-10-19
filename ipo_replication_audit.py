"""Independent rational payoff and direct-date cash-branch audit of fixed2025replication."""
import csv
from fractions import Fraction as F
import gzip
import json
from pathlib import Path
import zipfile

from research_runtime import atomic_json


def audit():
    out=Path('deliverables/ipo_replication_20261020');p=json.loads(Path('configs/ipo_replication_protocol_20261020.json').read_text())
    rows=json.loads((out/'matched_cases.json').read_text());summary=json.loads((out/'summary.json').read_text());saved=json.loads((out/'expected_amounts.json').read_text())
    with zipfile.ZipFile('inputs/ipo_replication_20261020/sources.retrieved.zip') as z:
        raw=json.loads(z.read('raw/2025.json'))['data'];original=[r for r in raw if r[4]=='初上市']
    assert [list(r['reported_fields'].values()) for r in rows]==original
    assert len({r['symbol'] for r in rows})==len(rows)
    eligible=[r for r in rows if r['eligible_for_calculation']];checks=[];probabilities=[]
    value=lambda v:F(str(v).replace(',',''))
    with gzip.open(p['calendar_path'],'rt') as source:calendar=[r['date'] for r in csv.DictReader(source)]
    for r in eligible:
        f=r['reported_fields'];probabilities.append(min(F(1),value(f['實際承銷股數'])/value(f['申購股數'])/value(f['總合格件'])))
    for drag in p['sale_drag_scenarios']:
        amounts=[]
        for r,prob in zip(eligible,probabilities):
            f=r['reported_fields'];principal=value(f['承銷價(元)'])*value(f['申購股數']);sale=value(r['raw_listing_quote']['open'])*value(f['申購股數'])*(1-F(drag))
            winner=sale-principal-value(p['application_fee_scenario'])-value(p['winner_fee_scenario']);loser=-value(p['application_fee_scenario'])
            ev=prob*winner+(1-prob)*loser;amounts.append(ev)
            observed=next(s for s in saved if s['symbol']==r['symbol'] and s['sale_drag']==drag)
            assert abs(value_signed(observed['expected_twd'])-ev)<F(1,10**18)
        ordered=sorted(amounts);n=len(ordered);median=ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2
        s=next(s for s in summary['scenarios'] if s['sale_drag']==drag)
        assert abs(value_signed(s['partial_sum_twd'])-sum(amounts))<F(1,10**18)
        assert abs(value_signed(s['median_expected_twd'])-median)<F(1,10**18)
        assert s['positive_events']==sum(v>0 for v in amounts)
        # Independent date snapshots: compute loser and winner cumulative cash separately for each case.
        event_times=set();timing=[]
        for r in eligible:
            reserve=r['application_end'];refund=calendar[calendar.index(r['draw_date'])+1];settlement=calendar[calendar.index(r['listing_date'])+2]
            timing.append((reserve,refund,settlement));event_times.update([(reserve,0),(refund,1),(settlement,1)])
        minimum=F(0)
        for when in sorted(event_times):
            minimum_cash=F(0)
            for r,(reserve,refund,settlement) in zip(eligible,timing):
                if when<(reserve,0):continue
                f=r['reported_fields'];principal=value(f['承銷價(元)'])*value(f['申購股數']);paid=principal+value(p['application_fee_scenario'])+value(p['winner_fee_scenario'])
                loser=-paid+(principal+value(p['winner_fee_scenario']) if when>=(refund,1) else 0)
                winner=-paid+(value(r['raw_listing_quote']['open'])*value(f['申購股數'])*(1-F(drag)) if when>=(settlement,1) else 0)
                minimum_cash+=min(loser,winner)
            minimum=min(minimum,minimum_cash)
        funding=next(s for s in summary['funding'] if s['sale_drag']==drag)
        assert F(funding['maximum_required_initial_cash_exact'])==-minimum
        checks.append(dict(sale_drag=drag,events=n,sum_expected_exact=str(sum(amounts)),median_expected_exact=str(median),cash_snapshot_times_verified=len(event_times),maximum_required_initial_cash_exact=str(-minimum)))
    coverage=not summary['gaps'] and not summary['unknown_budget_symbols'] and bool(eligible)
    gate=None if not coverage else all(F(c['sum_expected_exact'])>0 and F(c['median_expected_exact'])>0 for c in checks)
    assert gate==summary['exploratory_resource_gate_passed']
    assert coverage==summary['whole_affordable_cohort_coverage']
    union=max(F(0),1-sum(probabilities));independent=F(1)
    for probability in probabilities:independent*=1-probability
    assert F(summary['no_win_probability_lower_bound_exact'])==union
    assert F(summary['independent_no_win_illustration_exact'])==independent
    atomic_json(out/'independent_audit.json',dict(status='passed',original_whole_cohort_rows_verified=len(original),scenario_rows_verified=len(saved),checks=checks,gate=gate,method='Direct winner/loser fractions, all original source rows and per-date cash snapshots; no borrowing production payoff/funding helpers'))


def value_signed(v):return F(str(v))


if __name__=='__main__':audit()

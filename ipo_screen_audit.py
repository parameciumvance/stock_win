"""Independent exact-rational audit of fixed IPO conditional cash expressions."""
import datetime as dt
from fractions import Fraction as F
import json
from pathlib import Path

from research_runtime import atomic_json,sha256

OUT=Path('deliverables/ipo_screen_20261019')


def run():
    rows=json.loads((OUT/'matched_cases.json').read_text())
    eligible=[r for r in rows if r['eligible_for_calculation']]
    saved=json.loads((OUT/'expected_amounts.json').read_text())
    if len(saved)!=2*len(eligible):raise ValueError('Unexpected scenario count')
    source={r['symbol']:r for r in eligible};maximum=F(0);probabilities=[]
    for r in eligible:
        v=r['reported_fields'];q=F(v['申購股數'].replace(',',''));n=F(v['總合格件'].replace(',',''));lots=F(v['實際承銷股數'].replace(',',''))/q
        probabilities.append(min(F(1),lots/n))
    for s in saved:
        r=source[s['symbol']];v=r['reported_fields'];q=F(v['申購股數'].replace(',',''));n=F(v['總合格件'].replace(',',''));p=min(F(1),F(v['實際承銷股數'].replace(',',''))/q/n)
        offer=F(v['承銷價(元)'].replace(',',''));opening=F(r['raw_listing_quote']['open']);drag=F(s['sale_drag'])
        # Explicit winner and loser branches, instead of the production expression.
        winner=q*opening-q*offer-q*opening*drag-F(50)-F(20)
        loser=-F(20)
        exact=p*winner+(1-p)*loser
        difference=abs(exact-F(s['expected_application_twd']));maximum=max(maximum,difference)
        if difference>F(1,10**18):raise ValueError('Conditional payoff differs')
    summary=json.loads((OUT/'summary.json').read_text());no_win=max(F(0),F(1)-sum(probabilities));product=F(1)
    for p in probabilities:product*=1-p
    if abs(no_win-F(summary['no_win_probability_lower_bound_union']))>F(1,10**24) or abs(product-F(summary['independent_lottery_no_win_probability_illustration']))>F(1,10**24):raise ValueError('No-win probability differs')
    start=min(dt.date.fromisoformat(r['application_end']) for r in eligible);end=max(dt.date.fromisoformat(r['listing_date']) for r in eligible)
    peak=F(0)
    for offset in range((end-start).days+1):
        day=(start+dt.timedelta(days=offset)).isoformat();total=F(0)
        for r in eligible:
            if r['application_end']<=day<=r['listing_date']:
                v=r['reported_fields'];total+=F(v['承銷價(元)'].replace(',',''))*F(v['申購股數'].replace(',',''))+70
        peak=max(peak,total)
    if peak!=F(summary['reservation_overlap_through_listing_twd']):raise ValueError('Calendar-day reservation overlap differs')
    atomic_json(OUT/'independent_audit.json',dict(status='passed_exact_rational_conditional_cash_and_probability_checks',scenario_rows=len(saved),maximum_twd_difference=str(float(maximum)),calendar_days_checked=(end-start).days+1,peak_reservation_twd=str(peak),method='Exact Fraction; winner/loser branches plus every calendar day. No inference of executable fills, historicalPIT or future lottery probabilities.',inputs={str(p):sha256(p) for p in [OUT/'matched_cases.json',OUT/'expected_amounts.json',OUT/'summary.json']}))


if __name__=='__main__':run()

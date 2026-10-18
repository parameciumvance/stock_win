"""Literal typed guidance; interval diagnostics are not point forecast scores."""
from decimal import Decimal
import math
import re
from statistics import mean
from operating_snapshot import normalize,quarter_index

WORDS=['first','second','third','fourth']


def next_quarter(quarter):
    n=quarter_index(quarter)+1
    return f'{n//4}Q{n%4+1}'


def _target_matches(context,target):
    mentions=re.findall(r'\b(first|second|third|fourth)\s+quarter\s+(20\d{2})\b',context,re.I)
    return bool(mentions and mentions[-1][0].lower()==WORDS[int(target[-1])-1] and mentions[-1][1]==target[:4])


def extract_guidance(pages,issuer,origin_quarter):
    if issuer not in {'2330','2303'}:raise ValueError('Unsupported issuer')
    target=next_quarter(origin_quarter);matches=[]
    for page_number,page in enumerate(pages,1):
        text=normalize(page)
        if issuer=='2330':
            for m in re.finditer(r'Gross profit margin is expected to be between\s*(\d+(?:\.\d+)?)%\s+and\s*(\d+(?:\.\d+)?)%',text,re.I):
                context=text[max(0,m.start()-650):m.start()]
                if not _target_matches(context,target):raise ValueError('Guidance target quarter not explicitly confirmed')
                lo,hi=map(float,m.groups())
                if not 0<=lo<=hi<=100:raise ValueError('Invalid printed guidance interval')
                fx=re.findall(r'1 US dollar to (\d+(?:\.\d+)?) NT dollars',context,re.I)
                if len(set(fx))>1:raise ValueError('Ambiguous FX assumption')
                matches.append(dict(kind='closed_interval',lower_pct=lo,upper_pct=hi,lower_inclusive=True,upper_inclusive=True,
                    statement=m.group(0),source_page=page_number,assumed_fx_twd_per_usd=float(fx[0]) if fx else None,
                    conditions='stated USD/TWD exchange-rate assumption' if fx else None,condition_realization_verified=False,
                    finite_interval_diagnostics_eligible=True,point_forecast=None))
        else:
            starts=list(re.finditer(r'Gross Profit Margin:\s*',text,re.I))
            for m in starts:
                context=text[max(0,m.start()-450):m.start()]
                if not _target_matches(context,target):raise ValueError('UMC guidance target quarter not explicitly confirmed')
                remainder=text[m.end():]
                end=re.search(r'(?:[⚫•●]|Capacity Utilization:|Recent Developments|CAPEX:)',remainder,re.I)
                if not end:raise ValueError('Unterminated UMC guidance statement')
                statement=remainder[:end.start()].strip()
                if not statement or len(statement)>250:raise ValueError('Empty/unbounded guidance statement')
                item=dict(kind='qualitative',statement=statement,source_page=page_number,point_forecast=None,
                          finite_interval_diagnostics_eligible=False,lower_pct=None,upper_pct=None,
                          conditions=None,condition_realization_verified=False)
                lower=re.fullmatch(r'Will be higher than (\d+(?:\.\d+)?)%\s*(.*)',statement,re.I)
                if lower:
                    threshold=float(lower[1])
                    if not 0<=threshold<=100:raise ValueError('Invalid lower bound')
                    item.update(kind='strict_lower_bound',lower_pct=threshold,lower_inclusive=False,conditions=lower[2] or None)
                elif re.search(r'Q[1-4] gross margin',statement,re.I):
                    item.update(kind='relative_qualitative',conditions=statement[statement.lower().index('subject to'):] if 'subject to' in statement.lower() else None)
                elif re.search(r'approximately|close to',statement,re.I):
                    item['kind']='approximate_qualitative'
                matches.append(item)
    if len(matches)>1:raise ValueError('Multiple guidance statements; version/location review required')
    result=matches[0] if matches else dict(kind='unavailable',statement=None,source_page=None,point_forecast=None,
        finite_interval_diagnostics_eligible=False,lower_pct=None,upper_pct=None,conditions=None,condition_realization_verified=False)
    return dict(result,issuer=issuer,origin_quarter=origin_quarter,target_quarter=target,
                ready_for_historical_model=False,first_published_at=None)


def interval_diagnostics(actual,lower,upper):
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in [actual,lower,upper]) or lower>upper:
        raise ValueError('Invalid interval diagnostic inputs')
    a,lo,hi=(Decimal(str(v)) for v in [actual,lower,upper])
    below=max(Decimal(0),lo-a);above=max(Decimal(0),a-hi)
    return dict(contained=lo<=a<=hi,direction='below' if below else 'above' if above else 'inside',
                distance_pp=float(below+above),below_pp=float(below),above_pp=float(above),width_pp=float(hi-lo))


def compare(panel,guidance,protocol):
    pairs=[(r['issuer'],r['quarter']) for r in panel]
    expected={(i,q) for i in protocol['issuers'] for q in protocol['origin_quarters']}
    if len(pairs)!=len(expected) or set(pairs)!=expected:raise ValueError('Panel cohort missing or duplicate')
    if any(r['ready_for_historical_model'] is not False for r in panel):raise ValueError('Historical readiness unexpectedly promoted')
    by_pair=dict(zip(pairs,panel));forecasts={}
    for record in guidance:
        key=(record['issuer'],record['origin_quarter'])
        if key in forecasts or record['target_quarter']!=next_quarter(record['origin_quarter']):raise ValueError('Duplicate/misaligned guidance')
        if record['point_forecast'] is not None or record['ready_for_historical_model'] is not False:raise ValueError('Invented point forecast/readiness')
        if record.get('condition_realization_verified') is not False or record.get('first_published_at') is not None:raise ValueError('Unverified condition/publication promoted')
        if record['kind']!='closed_interval' and record['finite_interval_diagnostics_eligible']:raise ValueError('Non-interval guidance eligibility mismatch')
        forecasts[key]=record
    if set(forecasts)!=expected:raise ValueError('Guidance source cohort mismatch')
    comparisons=[];summaries=[]
    for issuer in protocol['issuers']:
        for target in protocol['comparison_targets']:
            n=quarter_index(target)-1;origin=f'{n//4}Q{n%4+1}';g=forecasts[(issuer,origin)];actual=by_pair[(issuer,target)]
            gm=actual['gross_margin_pct']
            if not isinstance(gm,(int,float)) or not math.isfinite(gm):raise ValueError('Missing target actual')
            row=dict(issuer=issuer,target_quarter=target,origin_quarter=origin,actual_gross_margin_pct=gm,
                guidance_kind=g['kind'],guidance_statement=g['statement'],guidance_page=g['source_page'],
                guidance_source_sha256=g['source_sha256'],guidance_source_url=g['source_url'],
                lower_pct=g.get('lower_pct'),upper_pct=g.get('upper_pct'),conditions=g.get('conditions'),
                assumed_fx_twd_per_usd=g.get('assumed_fx_twd_per_usd'),condition_realization_verified=False,
                previous_quarter_gm=by_pair[(issuer,origin)]['gross_margin_pct'],
                actual_accounting_standard_explicit=actual['accounting_standard_explicit'],
                origin_accounting_standard_explicit=by_pair[(issuer,origin)]['accounting_standard_explicit'],
                contained=None,direction=None,distance_pp=None,width_pp=None,threshold_predicate_satisfied=None,
                finite_interval_diagnostics_eligible=False,ready_for_historical_model=False)
            if g['kind']=='closed_interval':
                if g['finite_interval_diagnostics_eligible'] is not True or g.get('lower_inclusive') is not True or g.get('upper_inclusive') is not True:raise ValueError('Interval eligibility/boundary mismatch')
                row.update(interval_diagnostics(gm,g['lower_pct'],g['upper_pct']),finite_interval_diagnostics_eligible=True,unscored_reason=None)
            elif g['kind']=='strict_lower_bound':
                row.update(threshold_predicate_satisfied=Decimal(str(gm))>Decimal(str(g['lower_pct'])),
                           unscored_reason='One-sided strict bound; condition unverified; arithmetic predicate only, excluded from finite-interval aggregates')
            else:
                if g['finite_interval_diagnostics_eligible']:raise ValueError('Qualitative guidance must not be scored')
                row['unscored_reason']='No unambiguous finite numeric interval; no tolerance/point estimate invented'
            comparisons.append(row)
        rows=[r for r in comparisons if r['issuer']==issuer];scored=[r for r in rows if r['finite_interval_diagnostics_eligible']]
        summaries.append(dict(issuer=issuer,requested_targets=len(rows),finite_intervals=len(scored),unscored_targets=len(rows)-len(scored),
            contained=sum(r['contained'] for r in scored),above=sum(r['direction']=='above' for r in scored),below=sum(r['direction']=='below' for r in scored),
            realized_containment_fraction=sum(r['contained'] for r in scored)/len(scored) if scored else None,
            mean_outside_distance_pp=mean(r['distance_pp'] for r in scored) if scored else None,
            mean_printed_width_pp=mean(r['width_pp'] for r in scored) if scored else None))
    return comparisons,dict(results=summaries,total_requested_targets=len(comparisons),first_publication_verified=False,
        condition_realization_verified=False,point_mae_comparison_valid=False,forecast_skill_established=False,
        ready_for_historical_model=False,models_fitted=0,manual_download_requests=0)

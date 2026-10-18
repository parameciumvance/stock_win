"""Evidence extraction and retrospective arithmetic; never claims point-in-time validity."""
from datetime import date
import calendar
import math
import re
from statistics import mean,median

WORDS=['first','second','third','fourth']
MONTHS='January February March April May June July August September October November December'.split()


def quarter_index(q):
    if not re.fullmatch(r'20\d{2}Q[1-4]',q):raise ValueError('Invalid financial quarter')
    return int(q[:4])*4+int(q[-1])-1


def normalize(text):
    text=re.sub(r'(?<=\d)\.\s+(?=\d)', '.', ' '.join(text.split()))
    return re.sub(r'\b(20\d)\s+(\d)\b',r'\1\2',text)


def extract_financials(first_page,*,issuer,quarter,management=False):
    quarter_index(quarter)
    text=normalize(first_page);low=text.lower();year,n=int(quarter[:4]),int(quarter[-1]);word=WORDS[n-1]
    if issuer not in {'2303','2330'}:raise ValueError('Unsupported issuer')
    if issuer=='2303':
        if not all(s in low for s in ['united microelectronics',f'umc reports {word} quarter {year} results','twse: 2303','consolidated','tifrs']):raise ValueError('UMC identity/quarter/accounting basis missing')
        patterns=dict(gross_margin_pct=r'Gross margin:\s*(-?\d+(?:\.\d+)?)%',eps_twd=r'Earnings per share:\s*NT\$\s*(-?\d+(?:\.\d+)?)',revenue_twd_billions=r'Revenue:\s*NT\$\s*([\d,.]+) billion')
    else:
        identity=f'{word} quarter {year}' if management else f'{word} quarter ended {MONTHS[n*3-1]} {calendar.monthrange(year,n*3)[1]}, {year}'
        if 'tsmc' not in low or identity.lower() not in low or 'consolidated' not in low or ('tifrs' not in low and not management):raise ValueError('TSMC identity/quarter/accounting basis missing')
        patterns=dict(gross_margin_pct=r'Gross margin (?:for the quarter )?was\s*(-?\d+(?:\.\d+)?)%',eps_twd=r'diluted earnings per share of NT\$\s*(-?\d+(?:\.\d+)?)',revenue_twd_billions=r'consolidated revenue of NT\$\s*([\d,.]+) billion')
        if management:
            # Use the narrative with explicit NT$ billion units, not an ambiguous table column.
            patterns=dict(gross_margin_pct=r'Gross margin was\s*(-?\d+(?:\.\d+)?)%',eps_twd=r'diluted EPS was\s*NT\$\s*(-?\d+(?:\.\d+)?)',revenue_twd_billions=r'Net revenue was NT\$\s*([\d,.]+) billion')
    values={}
    for key,pattern in patterns.items():
        found=[float(v.replace(',','')) for v in re.findall(pattern,text,re.I)]
        if len(set(found))!=1:raise ValueError('Missing/conflicting '+key+': '+repr(found))
        values[key]=found[0]
    if not all(math.isfinite(v) for v in values.values()) or values['revenue_twd_billions']<=0 or values['gross_margin_pct']>100:raise ValueError('Invalid financial units/value')
    dates=re.findall(r'('+'|'.join(MONTHS)+r')\s+(\d{1,2})\s*,?\s+(20\d{2})',text)
    period_end=date(year,n*3,calendar.monthrange(year,n*3)[1]);releases=[]
    for month,day,y in dates:
        d=date(int(y),MONTHS.index(month)+1,int(day))
        if period_end<d and d.year<=year+1:releases.append(d.isoformat())
    if not releases:raise ValueError('No printed post-period document date')
    return dict(issuer=issuer,quarter=quarter,**values,visible_document_date=releases[0],accounting_basis='consolidated; standard not stated' if management else 'TIFRS consolidated',accounting_standard_explicit=not management,
                basis_evidence='consolidated basis explicit; this management document does not state TIFRS, so no TIFRS verification claimed' if management else 'explicit in earnings release',
                ready_for_historical_model=False,first_published_at=None)


def extract_guidance(text,issuer,quarter):
    text=normalize(text);target=quarter_index(quarter)+1;target=f'{target//4}Q{target%4+1}'
    if issuer=='2330':
        matches=re.findall(r'Gross profit margin is expected to be between\s*([\d.]+)%\s*and\s*([\d.]+)%',text,re.I)
        if len(matches)==1:
            lower,upper=map(float,matches[0])
            if not 0<=lower<=upper<=100:raise ValueError('Invalid guidance interval')
            return dict(target_quarter=target,kind='interval',lower_pct=lower,upper_pct=upper,point_forecast=None)
    fragments=re.findall(r'Gross Profit Margin:\s*([^\n]{1,200})',text,re.I) if issuer=='2303' else []
    return dict(target_quarter=target,kind='verbatim_or_unavailable',excerpt=fragments[0] if len(fragments)==1 else None,
                point_forecast=None,reason='Preserve conditional/qualitative/range wording without inventing a point forecast')


def arithmetic(panel,protocol):
    expected={(i,q) for i in protocol['issuers'] for q in protocol['quarters']}
    if len(panel)!=len(expected) or {(r['issuer'],r['quarter']) for r in panel}!=expected:raise ValueError('Cohort missing/duplicate rows')
    if any(r.get('ready_for_historical_model') is not False for r in panel):raise ValueError('Snapshot must not promote historical readiness')
    values={(r['issuer'],quarter_index(r['quarter'])):r.get('gross_margin_pct') for r in panel};basis={(r['issuer'],quarter_index(r['quarter'])):r.get('accounting_standard_explicit',False) for r in panel};errors=[];summary=[]
    for issuer in protocol['issuers']:
        paired=[]
        for q in protocol['evaluation_quarters']:
            n=quarter_index(q);target=values[(issuer,n)];prev=values.get((issuer,n-1));season=values.get((issuer,n-4))
            if any(v is None for v in [target,prev,season]):continue
            if not all(math.isfinite(v) for v in [target,prev,season]):raise ValueError('Nonfinite panel value')
            paired.append(dict(issuer=issuer,target_quarter=q,target_gross_margin_pct=target,previous_quarter=prev,same_quarter_previous_year=season,
                               previous_quarter_abs_error_pp=abs(target-prev),same_quarter_previous_year_abs_error_pp=abs(target-season),
                               accounting_standard_explicit_all_three=basis[(issuer,n)] and basis[(issuer,n-1)] and basis[(issuer,n-4)]))
        errors+=paired
        for method in protocol['arithmetic_baselines']:
            vals=[r[method+'_abs_error_pp'] for r in paired]
            summary.append(dict(issuer=issuer,method=method,paired_targets=len(paired),expected_targets=len(protocol['evaluation_quarters']),complete=len(paired)==len(protocol['evaluation_quarters']),
                mae_pp=mean(vals) if vals else None,median_ae_pp=median(vals) if vals else None))
    return errors,dict(label='Retrospective as-retrieved arithmetic; not PIT forecast validation',results=summary,accounting_standard_unstated_rows=sum(not r.get('accounting_standard_explicit',False) for r in panel),models_fitted=0,ready_for_historical_model=False)

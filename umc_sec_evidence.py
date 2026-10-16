"""UMC release checks and explicit conflicts between independently preserved clocks."""
from datetime import datetime,timezone
import re


def extract_umc_sec_text(text):
    text=' '.join(text.split())
    required=['UMC Reports Fourth Quarter 2024 Results','TWSE: 2303','January 21, 2025',
              'consolidated operating results for the fourth quarter of 2024']
    if not all(s in text for s in required):raise ValueError('SEC exhibit issuer/quarter/date/consolidation not confirmed')
    def unique(pattern):
        values=re.findall(pattern,text)
        if len(set(values))!=1:raise ValueError('Missing/conflicting SEC financial field')
        return float(values[0])
    margin=unique(r'Gross margin:\s*([\d.]+)%');eps=unique(r'Earnings per share:\s*NT\$([\d.]+)')
    revenue=unique(r'Revenue:\s*NT\$([\d.]+) billion')
    if not 0<=margin<=100 or revenue<=0:raise ValueError('Invalid financial value')
    return dict(issuer='2303',quarter='2024Q4',visible_release_date='2025-01-21',gross_margin_pct=margin,
                eps_twd=eps,revenue_twd_billions=revenue,consolidated_basis_explicit=True,
                accounting_standard_explicit='TIFRS' if 'TIFRS' in text else None)


def guidance_umc(text):
    text=' '.join(text.split())
    if 'First Quarter 2025 Outlook & Guidance' not in text:raise ValueError('Wrong UMC guidance target')
    values=re.findall(r'Gross Profit Margin:\s*Will be higher than ([\d.]+)% with 0121 earthquake impact',text)
    if len(values)!=1:raise ValueError('Missing/ambiguous UMC guidance predicate')
    threshold=float(values[0])
    if not 0<=threshold<=100:raise ValueError('Invalid UMC guidance threshold')
    return dict(target_quarter='2025Q1',operator='>',threshold_pct=threshold,condition='with 0121 earthquake impact',
                point_forecast=None,ready_for_evaluation=False)


def reconcile_clocks(header_clock,reported):
    sgml=datetime.fromisoformat(header_clock['utc'])
    index=datetime.fromisoformat(reported.replace('Z','+00:00'))
    if sgml.tzinfo is None or index.tzinfo is None:raise ValueError('Timezone-less acceptance clock')
    delta=(index.astimezone(timezone.utc)-sgml.astimezone(timezone.utc)).total_seconds()
    match=delta==0
    return dict(status='match' if match else 'conflict',matches=match,delta_seconds_json_minus_sgml=delta,
                sgml_raw=header_clock['raw'],sgml_eastern_interpretation=header_clock['eastern'],sgml_utc_interpretation=header_clock['utc'],
                sgml_taipei_interpretation=header_clock['taipei'],json_as_reported=reported,
                json_claimed_utc=index.astimezone(timezone.utc).isoformat(),
                canonical_sec_accepted_at=None,public_dissemination_at=None,
                policy='Compare preserved values without repairing either source; a match alone does not establish public dissemination or first Taiwan disclosure')

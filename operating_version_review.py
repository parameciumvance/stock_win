"""Inventory potential versions without mistaking an index for amendment coverage."""
from datetime import date, datetime
import json
import re
from sec_submissions_index import _unique_keys


def review_index(body, *, cik, company_fragment, start, end, period_end, anchor_accession):
    start, end, period = date.fromisoformat(start), date.fromisoformat(end), date.fromisoformat(period_end)
    if start > end or period >= start:
        raise ValueError('Invalid review window/financial period')
    obj = json.loads(body.decode('utf-8-sig'), object_pairs_hook=_unique_keys)
    if str(obj.get('cik','')).zfill(10) != cik or company_fragment.upper() not in obj.get('name','').upper():
        raise ValueError('Wrong submissions issuer')
    recent = obj['filings']['recent']
    keys = ['accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument']
    if any(not isinstance(recent.get(k),list) for k in keys):
        raise ValueError('Missing recent arrays')
    n = len(recent['accessionNumber'])
    if any(len(v) != n for v in recent.values() if isinstance(v,list)):
        raise ValueError('Misaligned recent arrays')
    if len(set(recent['accessionNumber'])) != n:
        raise ValueError('Duplicate accession')
    archives = obj['filings'].get('files')
    if not isinstance(archives,list):
        raise ValueError('Missing historical index coverage metadata')
    candidates = []
    all_dates = [date.fromisoformat(d) for d in recent['filingDate']]
    for i,d in enumerate(all_dates):
        form = recent['form'][i]
        if not start <= d <= end or form not in {'6-K','6-K/A','20-F','20-F/A'}:
            continue
        accession, primary = recent['accessionNumber'][i], recent['primaryDocument'][i]
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession) or not re.fullmatch(r'[A-Za-z0-9_.-]+',primary) or primary in {'.','..'}:
            raise ValueError('Unsafe candidate path')
        reported = recent['acceptanceDateTime'][i]
        if datetime.fromisoformat(reported.replace('Z','+00:00')).tzinfo is None:
            raise ValueError('Naive candidate acceptance clock')
        report = recent['reportDate'][i]
        if report:
            date.fromisoformat(report)
        base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
        candidates.append(dict(accession=accession, filing_date=d.isoformat(), report_date_as_reported=report,
            form=form, primary_document=primary, acceptance_as_reported=reported,
            relation='anchor' if accession == anchor_accession else 'explicit_amendment_candidate' if form.endswith('/A') else 'same_period_end_later_filing_candidate' if report == period.isoformat() else 'other_filing_requires_content_review',
            complete_submission_url=base+accession+'.txt', index_url=base+accession+'-index.html',
            financial_quarter_not_inferred_from_index=True, original_availability_not_inferred_from_index=True))
    if sum(c['relation']=='anchor' for c in candidates) != 1:
        raise ValueError('Anchor missing/ambiguous in review window')
    return dict(cik=cik, recent_rows=n, recent_min_date=min(all_dates).isoformat(), recent_max_date=max(all_dates).isoformat(),
        review_start=start.isoformat(), review_end=end.isoformat(), period_end=period.isoformat(),
        candidates=sorted(candidates,key=lambda c:(c['filing_date'],c['accession'])), historical_files_as_reported=archives,
        explicit_amendment_candidates=sum(c['form'].endswith('/A') for c in candidates),
        index_snapshot_only=True, full_revision_history_verified=False, ready_for_model=False,
        limitations='Absence of /A does not prove absence of later financial versions, ordinary 6-K updates, deleted filings, or SEC post-acceptance corrections. Window is a document-review scope, not a prediction cutoff. No JSON clock is promoted.')


def classify_time(kind, value, *, source_url, raw_obtained):
    """Prevent schedule/date/transport clocks being promoted as publication."""
    labels = {'issuer_date':'date_only', 'conference_schedule':'scheduled_event_only',
              'sec_acceptance':'acceptance_only', 'transport_observation':'retrieval_only',
              'usual_process_duration':'not_a_per_document_time_bound'}
    if kind not in labels:
        raise ValueError('Unreviewed time evidence kind')
    return dict(kind=kind, as_reported=value, source_url=source_url, raw_obtained=raw_obtained,
                classification=labels[kind], public_dissemination_at=None, taiwan_first_published_at=None,
                ready_for_model=False)

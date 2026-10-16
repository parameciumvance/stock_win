"""Locate candidate earnings filings; submissions JSON alone never verifies timing."""
from datetime import date,datetime
import json
import re


def _unique_keys(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key: '+key)
        result[key]=value
    return result


def locate_candidates(body,*,cik,filing_date):
    obj=json.loads(body.decode('utf-8-sig'),object_pairs_hook=_unique_keys)
    if not isinstance(obj,dict):raise ValueError('Expected SEC submissions object')
    if str(obj.get('cik','')).zfill(10)!=cik:raise ValueError('Wrong SEC submissions issuer')
    if not isinstance(obj.get('name'),str) or 'UNITED MICROELECTRONICS' not in obj['name'].upper():raise ValueError('Wrong company name')
    target=date.fromisoformat(filing_date)
    recent=obj['filings']['recent']
    keys=['accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument']
    if any(not isinstance(recent.get(key),list) for key in keys):raise ValueError('Missing recent array')
    n=len(recent[keys[0]])
    if any(len(recent[key])!=n for key in keys):raise ValueError('Misaligned SEC submissions arrays')
    if len(set(recent['accessionNumber']))!=n:raise ValueError('Duplicate accession in recent filings')
    candidates=[]
    for i in range(n):
        if recent['filingDate'][i]!=target.isoformat() or recent['form'][i]!='6-K':continue
        accession=recent['accessionNumber'][i];primary=recent['primaryDocument'][i]
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession):raise ValueError('Unsafe/invalid accession')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',primary) or primary in ('.','..'):raise ValueError('Unsafe primary document')
        stamp=recent['acceptanceDateTime'][i]
        parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError('Naive submissions clock')
        base=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-","")}/'
        candidates.append(dict(accession=accession,filing_date=recent['filingDate'][i],report_date_as_reported=recent['reportDate'][i],form='6-K',primary_document=primary,
                               acceptanceDateTime_as_reported=stamp,acceptance_clock_verified=False,earnings_quarter_verified=False,
                               complete_submission_url=base+accession+'.txt',index_url=base+accession+'-index.htm',primary_url=base+primary))
    archives=obj['filings'].get('files',[])
    covering=[]
    if not candidates:
        for record in archives:
            if date.fromisoformat(record['filingFrom'])<=target<=date.fromisoformat(record['filingTo']):covering.append(record)
    return dict(cik=cik,company=obj['name'],recent_rows=n,target_filing_date=filing_date,candidates=candidates,
                archived_files_covering_target=covering,clock_policy='Preserve JSON clock verbatim; do not promote declared Z to verified UTC without original SGML/index crosscheck',ready_for_model=False)

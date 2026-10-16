"""Parse original SEC complete-submission SGML without inventing publication clocks."""
import calendar
from datetime import datetime, timezone
import hashlib
import re
from zoneinfo import ZoneInfo


def acceptance_clock(value):
    if not re.fullmatch(r'\d{14}',value):raise ValueError('Invalid SEC acceptance clock')
    naive=datetime.strptime(value,'%Y%m%d%H%M%S');zone=ZoneInfo('America/New_York')
    candidates=set()
    for fold in (0,1):
        utc=naive.replace(tzinfo=zone,fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None)==naive:candidates.add(utc)
    if len(candidates)!=1:raise ValueError('Ambiguous or nonexistent SEC Eastern clock')
    utc=candidates.pop()
    return dict(raw=value,timezone='America/New_York',eastern=utc.astimezone(zone).isoformat(),
                utc=utc.isoformat(),taipei=utc.astimezone(ZoneInfo('Asia/Taipei')).isoformat())


def parse_submission(body,*,cik,accession,quarter,report_event_date=None):
    if not body.startswith(b'<SEC-DOCUMENT>') or not body.rstrip().endswith(b'</SEC-DOCUMENT>'):
        raise ValueError('Expected complete SEC submission, not HTML, an exhibit, or truncated download')
    text=body.decode('utf-8')
    header_match=re.search(r'(?ms)^<SEC-HEADER>[^\n]*\n(.*?)^</SEC-HEADER>',text)
    if not header_match:raise ValueError('Missing SEC header')
    header=header_match[1]
    def one(pattern,source=header):
        values=re.findall(pattern,source,re.M)
        if len(values)!=1:raise ValueError('Missing/ambiguous SEC header field: '+pattern)
        return values[0]
    if one(r'^ACCESSION NUMBER:\s*([^\s]+)')!=accession or not text.startswith('<SEC-DOCUMENT>'+accession+'.txt '):
        raise ValueError('Wrong SEC accession')
    if one(r'^\s*CENTRAL INDEX KEY:\s*(\d+)')!=cik:raise ValueError('Wrong or ambiguous issuer CIK')
    if one(r'^CONFORMED SUBMISSION TYPE:\s*([^\s]+)')!='6-K':raise ValueError('Expected original 6-K form')
    company=one(r'^\s*COMPANY CONFORMED NAME:[ \t]*(.+)$').strip()
    period=one(r'^CONFORMED PERIOD OF REPORT:\s*(\d{8})')
    if not re.fullmatch(r'\d{4}Q[1-4]',quarter):raise ValueError('Invalid expected quarter')
    year=int(quarter[:4]);month=int(quarter[-1])*3
    expected=f'{year:04d}{month:02d}{calendar.monthrange(year,month)[1]:02d}'
    if report_event_date is not None:
        event=datetime.strptime(report_event_date,'%Y-%m-%d').date()
        if event<datetime.strptime(expected,'%Y%m%d').date():raise ValueError('Event date precedes expected financial quarter end')
        expected=event.strftime('%Y%m%d')
    if period!=expected:raise ValueError('SEC report period does not match expected quarter')
    clock=acceptance_clock(one(r'^<ACCEPTANCE-DATETIME>(\d{14})[ \t]*$'))
    filed=one(r'^FILED AS OF DATE:\s*(\d{8})')
    if datetime.fromisoformat(clock['eastern']).date()<datetime.strptime(period,'%Y%m%d').date():
        raise ValueError('Acceptance precedes report period')
    if datetime.strptime(filed,'%Y%m%d').date()<datetime.fromisoformat(clock['eastern']).date():
        raise ValueError('Filing date precedes acceptance date')
    count=int(one(r'^PUBLIC DOCUMENT COUNT:\s*(\d+)'))
    blocks=re.findall(rb'(?ms)^<DOCUMENT>[ \t]*\r?\n(.*?)^</DOCUMENT>[ \t]*(?:\r?\n|$)',body)
    if len(blocks)!=count or not blocks or len(re.findall(rb'(?m)^<DOCUMENT>[ \t]*\r?$',body))!=count:
        raise ValueError('Incomplete/incorrect public document count')
    docs=[]
    for block in blocks:
        prefix=block.split(b'<TEXT>',1)[0].decode('ascii')
        def field(tag):
            values=re.findall(r'^<'+tag+r'>([^\r\n]+)',prefix,re.M)
            if len(values)!=1:raise ValueError('Missing/ambiguous document '+tag)
            return values[0].strip()
        filename=field('FILENAME');sequence=int(field('SEQUENCE'));kind=field('TYPE')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',filename) or filename in ('.','..'):
            raise ValueError('Unsafe SEC document filename')
        match=re.search(rb'(?ms)^<TEXT>[ \t]*\r?\n(.*?)^</TEXT>[ \t]*(?:\r?\n|$)',block)
        if not match:raise ValueError('Truncated SEC document text')
        payload=match[1]
        docs.append(dict(filename=filename,sequence=sequence,type=kind,payload=payload,
                         payload_sha256=hashlib.sha256(payload).hexdigest(),payload_size_bytes=len(payload)))
    if len({d['filename'] for d in docs})!=count or sorted(d['sequence'] for d in docs)!=list(range(1,count+1)):
        raise ValueError('Duplicate filenames or document sequences')
    primary=[d for d in docs if d['type']=='6-K' and d['sequence']==1]
    if len(primary)!=1 or sum(d['type']=='6-K' for d in docs)!=1:raise ValueError('Missing/ambiguous primary 6-K')
    result=dict(cik=cik,company=company,accession=accession,form='6-K',quarter=quarter,period_of_report=period,
                filed_date=filed,acceptance=clock,document_count=count,primary_filename=primary[0]['filename'],documents=docs)
    if report_event_date is not None:
        result.update(report_period_kind='filing_event_date',quarter_match_requires_exhibit=True)
    return result

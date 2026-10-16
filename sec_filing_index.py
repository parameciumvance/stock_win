"""Strict document/clock checks for an archived SEC filing index HTML copy.

No scripts or local assets are executed. Index clocks corroborate a submission;
they never establish first public disclosure, dissemination, or version coverage.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
from sec_submission import acceptance_clock
from umc_sec_evidence import reconcile_clocks


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def find(self, tag):
        return [n for c in self.children if isinstance(c, Node) for n in ([c] if c.tag == tag else []) + c.find(tag)]


class Tree(HTMLParser):
    VOID = {'meta','link','img','br','hr','input','area','base','embed','param','source','track','wbr'}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        if not any(n.tag in {'script','style','noscript'} for n in self.stack):
            self.stack[-1].children.append(text)


def parse_filing_index(body, *, submission, source_url):
    """Check an index against a separately parsed complete submission."""
    text = body.decode('utf-8-sig', errors='strict')
    root = Tree(text).root
    accession, cik = submission['accession'], submission['cik']
    base = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
    if source_url not in {base+accession+'-index.html', base+accession+'-index.htm'}:
        raise ValueError('Unexpected index source URL')
    saved = re.findall(r'<!--\s*saved from url=\(\d+\)(\S+)\s*-->', text)
    if saved != [source_url]:
        raise ValueError('Missing or conflicting browser saved origin')
    titles = root.find('title')
    if len(titles) != 1 or titles[0].text() != 'EDGAR Filing Documents for '+accession:
        raise ValueError('Index accession title mismatch')
    company = [n for n in root.find('span') if 'companyName' in n.attrs.get('class','').split()]
    if len(company) != 1 or submission['company'].upper() not in company[0].text().upper():
        raise ValueError('Index filer name mismatch')
    cik_links = [a for a in company[0].find('a') if re.search(r'(?:\?|&)CIK='+cik+r'(?:&|$)', a.attrs.get('href',''))]
    if len(cik_links) != 1:
        raise ValueError('Index CIK mismatch')
    forms = [n for n in root.find('div') if n.attrs.get('id') == 'formName']
    accessions = [n for n in root.find('div') if n.attrs.get('id') == 'secNum']
    if len(forms) != 1 or not forms[0].text().startswith('Form '+submission['form']+' '):
        raise ValueError('Index form mismatch')
    if len(accessions) != 1 or re.findall(r'\d{10}-\d{2}-\d{6}', accessions[0].text()) != [accession]:
        raise ValueError('Index accession mismatch')
    fields = {}
    for parent in root.find('div'):
        children = [c for c in parent.children if isinstance(c, Node)]
        for i,child in enumerate(children):
            if 'infoHead' not in child.attrs.get('class','').split():
                continue
            key = child.text()
            if key in fields or i+1 == len(children) or 'info' not in children[i+1].attrs.get('class','').split():
                raise ValueError('Duplicate or unpaired index field')
            fields[key] = children[i+1].text()
    if not {'Accepted','Documents','Filing Date','Period of Report'} <= fields.keys():
        raise ValueError('Missing index fields')
    for field,key in [('Filing Date','filed_date'),('Period of Report','period_of_report')]:
        if fields[field].replace('-','') != submission[key]:
            raise ValueError('Index date mismatch')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', fields['Accepted']):
        raise ValueError('Malformed index Accepted clock')
    clock = acceptance_clock(datetime.strptime(fields['Accepted'], '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d%H%M%S'))
    if clock != submission['acceptance']:
        raise ValueError('Index and SGML Accepted clocks disagree')
    tables = [n for n in root.find('table') if n.attrs.get('summary') == 'Document Format Files']
    if len(tables) != 1:
        raise ValueError('Missing or ambiguous document table')
    documents, complete = [], []
    for row in tables[0].find('tr'):
        cells = [c for c in row.children if isinstance(c, Node) and c.tag == 'td']
        if not cells:
            continue
        if len(cells) != 5:
            raise ValueError('Malformed index document row')
        links = cells[2].find('a')
        if len(links) != 1:
            raise ValueError('Ambiguous index document link')
        name = links[0].text()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or urljoin(source_url, links[0].attrs.get('href','')) != base+name:
            raise ValueError('Index document URL/filename mismatch')
        if urlsplit(base+name).scheme != 'https':
            raise ValueError('Non-HTTPS document URL')
        if not cells[4].text().isdigit():
            raise ValueError('Invalid index document size')
        size = int(cells[4].text())
        if cells[0].text():
            if not cells[0].text().isdigit():
                raise ValueError('Invalid document sequence')
            documents.append(dict(filename=name, sequence=int(cells[0].text()), type=cells[3].text(), index_size_bytes=size))
        else:
            if name != accession+'.txt' or cells[1].text() != 'Complete submission text file':
                raise ValueError('Unexpected complete submission row')
            complete.append(size)
    expected = [{k:d[k] for k in ['filename','sequence','type']} for d in submission['documents']]
    if [{k:d[k] for k in ['filename','sequence','type']} for d in documents] != expected:
        raise ValueError('Index documents do not match SGML')
    if fields['Documents'] != str(len(documents)) or len(documents) != submission['document_count']:
        raise ValueError('Index document count mismatch')
    if complete != [submission['source_size_bytes']]:
        raise ValueError('Complete submission byte size mismatch')
    modified = [n.attrs.get('content') for n in root.find('meta') if n.attrs.get('http-equiv','').lower() == 'last-modified']
    # This is saved HTML metadata, never an HTTP header or a publication timestamp.
    if len(modified) > 1:
        raise ValueError('Ambiguous Last-Modified metadata')
    modified_utc = None
    if modified:
        dt = parsedate_to_datetime(modified[0])
        if dt.tzinfo is None:
            raise ValueError('Timezone-less Last-Modified metadata')
        modified_utc = dt.astimezone(timezone.utc).isoformat()
    return dict(accession=accession, cik=cik, accepted_as_displayed=fields['Accepted'], acceptance=clock,
                documents=documents, complete_submission_size_bytes=complete[0],
                last_modified_html_meta_as_reported=modified[0] if modified else None,
                last_modified_html_meta_utc=modified_utc,
                last_modified_matches_interpreted_acceptance=modified_utc == clock['utc'] if modified else None,
                source_http_headers_available=False, representation='User browser-saved HTML',
                index_and_sgml_wallclock_match=True, dissemination_verified=False)


def corroborate_index(index, header_clock, json_reported):
    if index['acceptance'] != header_clock or index['index_and_sgml_wallclock_match'] is not True:
        raise ValueError('Index/header clock not corroborated')
    comparison = reconcile_clocks(header_clock, json_reported)
    return dict(comparison, status='sgml_index_corroborated_json_match' if comparison['matches'] else 'sgml_index_corroborated_json_conflict',
                json_conflict_retained=not comparison['matches'], canonical_sec_accepted_at=header_clock['taipei'],
                sec_accepted_time_corroborated=True, public_dissemination_at=None, taiwan_first_published_at=None,
                complete_revision_history_verified=False, ready_for_model=False,
                policy='Use matching complete-SGML and saved filing-index clocks as explicit SEC acceptance anchor under America/New_York interpretation; retain JSON discrepancy unmodified and do not infer its cause. Acceptance is not public dissemination or Taiwan first disclosure.')

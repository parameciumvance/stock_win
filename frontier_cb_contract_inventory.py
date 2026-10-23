"""Replay all declared HTML pointers and the saved CB API template evidence.

No JavaScript is executed, URL is requested, bond population selected or source
gate promoted. Script property matches are labelled literal evidence only.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo
import zipfile


OUT = Path('deliverables/frontier_cb_contract_20261022')
ENTRY_SHA256 = '95851a2b8a7668bb9461dbb2440134d5371b35fb6e4d9a043a16cc2a9c5fef9c'
ENTRY_BODY_SHA256 = 'b9404588f3fd054999d921ed145d3f5afa69a8d5cc8100ebe5cf1a0432a808eb'
OPTIONS_SHA256 = '7f9d3b6605d199c1821499d12a69da6965954b21443f0bb3ee02a3051b5ae60c'
OPTIONS_BODY_SHA256 = 'c942aed7eab7a183176aa5c9984559c171e60bc454740591f0373ea47b64686e'
REPORT_SHA256 = '01c86216ee132344d8349de1afbdd762a511fd261f28f8545ea012aecfaaa7da'
REPORT_BODY_SHA256 = 'ae7833385a794c2178957c82051e01c6a15f868193cb83c86df1b2dce4adf2fa'
SELECTION_SHA256 = '1d3845ebd01c06513eaf62cf688b5ed607d7804e6f88c085a079ef27531a293e'
CALENDAR_SHA256 = 'd56672ecfa1fcb94730e63d98f60e7ba994873e48e094b957afcc6d3cbbbe353'
CALENDAR_BODY_SHA256 = '841fca2c02fdabe3ef8a52b4ab1752b8d36b4a0274f05fa78b861739057272f1'
REPORT_FIELDS = ['發行機構代碼','發行機構名稱','債券名稱','掛牌日期','發行資料']
REPORT_QUERY_KEYS = {'TYPEK','bond_id','bond_kind','bond_subn','bond_yrn','come',
                     'encodeURIComponent','firstin','issuer_stock_code','monyr_reg','pg','step','tg'}
OLD_OUT = Path('deliverables/frontier_20261020')
OLD_SOURCES = {
    'route': ('57cfdeb2a684c86a457312f5d74eed3295d92072abfb629677ae121b32ebb1c5',
              'raw/main.js', 'cfbd8c64c748149f039f1d4f1c5b3ba4511039b9c9e60d8ed53fd9624edc587a'),
    'scripts': ('1cbd35217f2adbe54e42cee218436ffe48963b2d40b811f2465c02f973db4707',
                'raw/tables.js', '085fd65b4e15e2af4f3adb3f256f0058d0176dd2d98ce53217ede16667a04a90'),
}
POINTER_ATTRIBUTES = {'href', 'src', 'action'}
ATTRIBUTE = re.compile(r'''([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?''')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def _origin(url):
    parsed = urlsplit(url)
    return parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


def _http(url):
    parsed = urlsplit(url)
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password


class _Inventory(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pointers, self.forms, self.scripts, self.data_declarations = [], [], [], []
        self.form_stack, self.select, self.option, self.script = [], None, None, None
        self.title_depth, self.title_text, self.html_lang = 0, [], None

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        raw_fields = list(ATTRIBUTE.finditer(re.sub(r'^<\s*[^\s/>]+', '', raw)))
        line, column = self.getpos()
        for position, (name, value) in enumerate(attrs):
            literal = value
            if position < len(raw_fields):
                match = raw_fields[position]
                if match.group(1).lower() == name:
                    literal = next((value for value in match.groups()[1:] if value is not None), None)
            if name in POINTER_ATTRIBUTES:
                self.pointers.append(dict(occurrence=len(self.pointers)+1, tag=tag, attribute=name,
                    attribute_position=position, value=value, source_literal=literal,
                    line=line, column=column, followup_authorized=False))
            if name.startswith('data-'):
                self.data_declarations.append(dict(tag=tag,attribute=name,value=value,
                    source_literal=literal,line=line,column=column,followup_authorized=False))
        values = dict(attrs)
        if tag == 'html':
            self.html_lang = values.get('lang')
        if tag == 'title':
            self.title_depth += 1
        if tag == 'form':
            form = dict(attributes=attrs,action=values.get('action'),method=values.get('method'),
                        controls=[],followup_authorized=False)
            self.forms.append(form)
            self.form_stack.append(form)
        if tag in ('input','select','button','textarea') and self.form_stack:
            control = dict(tag=tag,name=values.get('name'),value=values.get('value'),attributes=attrs,
                           options=[],followup_authorized=False)
            self.form_stack[-1]['controls'].append(control)
            if tag == 'select':
                self.select = control
        if tag == 'option' and self.select is not None:
            self.option = dict(value=values.get('value'),text='',attributes=attrs,followup_authorized=False)
            self.select['options'].append(self.option)
        if tag == 'script':
            self.script = dict(src=values.get('src'),raw_text='',attributes=attrs,line=line,column=column,
                               followup_authorized=False)
            self.scripts.append(self.script)

    def handle_data(self, data):
        if self.script is not None:
            self.script['raw_text'] += data
        elif self.option is not None:
            self.option['text'] += data
        if self.title_depth:
            self.title_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'form' and self.form_stack:
            self.form_stack.pop()
        elif tag == 'select':
            self.select = self.option = None
        elif tag == 'option':
            self.option = None
        elif tag == 'script':
            self.script = None
        elif tag == 'title':
            self.title_depth = max(0,self.title_depth-1)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        self.handle_endtag(tag)


def inspect_html(body: bytes, effective_url: str) -> dict:
    require(isinstance(body,bytes) and body, 'Saved HTML body must be nonempty bytes')
    require(_http(effective_url), 'Effective source URL must be explicit HTTP(S)')
    declared = re.search(br'<meta\b[^>]*charset\s*=\s*["\']?([A-Za-z0-9_-]+)',body,re.I)
    charset = declared.group(1).decode('ascii') if declared else None
    encoding = {'utf8':'utf-8-sig','utf-8':'utf-8-sig','big5':'big5'}.get((charset or 'utf-8').lower())
    require(encoding is not None, 'Unsupported declared HTML charset')
    text = body.decode(encoding,errors='strict')
    parser = _Inventory()
    parser.feed(text)
    parser.close()
    bases = [pointer for pointer in parser.pointers if pointer['tag'] == 'base' and pointer['attribute'] == 'href']
    resolution_base = effective_url
    if bases:
        candidate = urljoin(effective_url,bases[0]['value']) if isinstance(bases[0]['value'],str) else None
        resolution_base = candidate if candidate is not None and _http(candidate) else None
    for pointer in parser.pointers:
        value = pointer['value']
        resolved = None
        if isinstance(value,str) and value:
            absolute = urlsplit(value).scheme or value.startswith('//')
            if absolute or resolution_base is not None:
                candidate = urljoin(effective_url if pointer['tag'] == 'base' else resolution_base or effective_url,value)
                resolved = candidate if _http(candidate) else None
        pointer.update(resolved_url=resolved,
                       same_origin=resolved is not None and _origin(resolved) == _origin(effective_url),
                       resolution_basis='first_base_href' if bases else 'effective_url')
        if resolution_base is None and not urlsplit(value or '').scheme:
            pointer['resolution_basis'] = 'unsupported_base_relative_unresolved'
    declarations = []
    for number, script in enumerate(parser.scripts,1):
        raw = script['raw_text']
        script['text_sha256'] = digest(raw.encode('utf-8'))
        for match in re.finditer(r'''\b(action|option|pattern)\s*:\s*(?:(["'])(.*?)\2|([A-Za-z_$][\w$]*))''',raw):
            declarations.append(dict(kind='script_property_literal_evidence_only',key=match.group(1),
                value=match.group(3),source_literal=match.group(0).split(':',1)[1].strip(),
                identifier=match.group(4),script_number=number,character_offset=match.start(),
                followup_authorized=False))
    return dict(status='saved_html_pointer_inventory_only',body_sha256=digest(body),size_bytes=len(body),
                declared_charset=charset,encoding=encoding,effective_url=effective_url,
                html_lang=parser.html_lang,title=''.join(parser.title_text),pointers=parser.pointers,
                forms=parser.forms,scripts=parser.scripts,literal_declarations=declarations,
                data_declarations=parser.data_declarations,base_href_declarations=bases,
                resolution_base=resolution_base,all_pointer_occurrences_retained=True,
                JavaScript_executed=False,script_properties_are_syntactically_unverified_evidence=True,
                bond_population_selected=False,complete_population_verified=False,
                cash_claim_source_gate_passed=False,source_gate_passed=False,historical_pit_verified=False)


def inspect_options(body: bytes) -> dict:
    def pairs(items):
        result = {}
        for name,value in items:
            require(name not in result,'Duplicate option JSON key')
            result[name] = value
        return result
    def invalid_constant(value):
        raise ValueError('Nonfinite option JSON value: '+value)
    require(isinstance(body,bytes) and body,'Saved option body must be nonempty bytes')
    payload = json.loads(body.decode('utf-8-sig',errors='strict'),object_pairs_hook=pairs,
                         parse_constant=invalid_constant)
    require(isinstance(payload,dict) and set(payload) == {'stat','options'} and payload['stat'] == 'ok'
            and isinstance(payload['options'],dict) and set(payload['options']) == {'bondIssuer'},
            'Unknown option response schema/status')
    options = payload['options']['bondIssuer']
    require(isinstance(options,list) and all(isinstance(item,dict) and set(item) == {'value','text'}
            and all(isinstance(value,str) for value in item.values()) for item in options),
            'Unknown issuer option row schema')
    require(len(options) == len({item['value'] for item in options}),'Duplicate issuer option value')
    return dict(status='all_returned_issuer_options_preserved',body_sha256=digest(body),size_bytes=len(body),
                returned_option_count=len(options),options=options,
                first_returned_option=options[0] if options else None,
                option_selection_performed=False,complete_bond_population_verified=False,
                cash_claim_source_gate_passed=False,source_gate_passed=False,historical_pit_verified=False)


def _strict_json(body):
    def pairs(items):
        result = {}
        for name,value in items:
            require(name not in result,'Duplicate report JSON key')
            result[name] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite report JSON value: '+value)
    require(isinstance(body,bytes) and body,'Saved report body must be nonempty bytes')
    return json.loads(body.decode('utf-8-sig',errors='strict'),object_pairs_hook=pairs,parse_constant=invalid)


def _row_digest(row):
    return digest(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode('utf-8'))


def inspect_report(body: bytes, effective_url: str = 'https://www.tpex.org.tw/www/zh-tw/bond/convSearch') -> dict:
    """Keep every returned row and literal link; no contract interpretation."""
    require(_http(effective_url),'Report effective URL must be HTTP(S)')
    payload = _strict_json(body)
    require(isinstance(payload,dict) and set(payload) == {'tables','stat'} and payload['stat'] == 'ok',
            'Unknown report response schema/status')
    tables = payload['tables']
    require(isinstance(tables,list) and len(tables) == 1 and isinstance(tables[0],dict),
            'Expected one report table')
    table = tables[0]
    require(set(table) == {'title','subtitle','date','fields','data','totalCount','notes','summary'}
            and all(isinstance(table[key],str) for key in ('title','subtitle','date'))
            and table['fields'] == REPORT_FIELDS and isinstance(table['notes'],list)
            and isinstance(table['summary'],list),'Unknown report table schema')
    data = table['data']
    require(isinstance(data,list) and all(isinstance(row,list) and len(row) == 5
            and all(isinstance(value,str) for value in row) for row in data),'Unknown report row schema')
    require(type(table['totalCount']) is int and table['totalCount'] == len(data),
            'Report declared count differs from returned rows')
    rows,seen = [],set()
    for number,row in enumerate(data,1):
        issuer,_,_,listed,url = row
        require(re.fullmatch(r'\d{4}',issuer) is not None,'Invalid report issuer code')
        require(re.fullmatch(r'\d{3}/\d{2}/\d{2}',listed) is not None,'Invalid listed date syntax')
        year,month,day = map(int,listed.split('/'))
        date(year+1911,month,day)
        parsed = urlsplit(url)
        require(parsed.scheme == 'https' and parsed.netloc == 'mopsov.twse.com.tw'
                and parsed.path == '/mops/web/t120sg01' and not parsed.fragment,
                'Unknown issuance-data link host/path')
        require(re.search(r'%(?![0-9a-fA-F]{2})',parsed.query) is None,'Invalid URL percent escape')
        pairs = parse_qsl(parsed.query,keep_blank_values=True,strict_parsing=True,errors='strict')
        require(len(pairs) == len({key for key,_ in pairs}),'Duplicate issuance-data URL query key')
        query = dict(pairs)
        require(set(query) == REPORT_QUERY_KEYS,'Unknown issuance-data URL query schema')
        bond = query['bond_id']
        require(re.fullmatch(r'\d+',bond) is not None and len(bond) > len(issuer)
                and query['issuer_stock_code'] == issuer and bond.startswith(issuer),
                'Issuance-data URL issuer/bond identity mismatch')
        require(bond not in seen,'Duplicate report bond_id')
        seen.add(bond)
        rows.append(dict(row_number=number,issuer=issuer,bond_code=bond,original_fields=row,
                         row_sha256=_row_digest(row),issuance_data_pointer=dict(
                         url=url,type='official_issuance_data_html_interface_uninspected',
                         decoded_query=query,followup_authorized=False,
                         PDF_verified=False,holder_put_contract_verified=False)))
    subtitle = inspect_html(table['subtitle'].encode('utf-8'),effective_url) if table['subtitle'] else None
    return dict(status='all_returned_cb_report_rows_and_links_preserved',body_sha256=digest(body),
                size_bytes=len(body),effective_url=effective_url,title=table['title'],date=table['date'],
                fields=table['fields'],subtitle_original=table['subtitle'],notes_original=table['notes'],
                summary_original=table['summary'],declared_total=table['totalCount'],
                returned_row_count=len(rows),count_reconciliation_passed=True,rows=rows,
                subtitle_pointers=subtitle['pointers'] if subtitle else [],
                complete_bond_population_verified=False,holder_put_contracts_verified=False,
                cash_claim_source_gate_passed=False,source_gate_passed=False,historical_pit_verified=False)


def _saved(root, out, batch, expected):
    package = json.loads((root/out/(batch+'_package.json')).read_bytes())
    transfer = json.loads((root/Path(package['transfer_receipt'])).read_bytes())
    require(package['sha256'] == transfer['sha256'] == expected and transfer['roundtrip_verified'] is True,
            'Pinned readback receipt mismatch')
    body = (root/Path(package['retrieved'])).read_bytes()
    require(digest(body) == expected, 'Source archive SHA mismatch')
    with zipfile.ZipFile(root/Path(package['retrieved'])) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None,'Archive duplicate/CRC failure')
        manifest = json.loads(archive.read('manifest.json'))
        require(set(names) == set(manifest)|{'manifest.json'}, 'Archive manifest population mismatch')
        members = {name:archive.read(name) for name in names}
        for name,wanted in manifest.items():
            require(digest(members[name]) == wanted,'Archive inner SHA mismatch')
    require(package['manifest_files'] == len(manifest),'Package manifest count mismatch')
    return members,dict(path=package['retrieved'],sha256=expected,manifest_files=len(manifest),crc_manifest_verified=True)


def inventory(root: Path | str = '.') -> dict:
    root = Path(root)
    members,archive = _saved(root,OUT,'entry',ENTRY_SHA256)
    body = members['raw/cb_listed.html']
    require(digest(body) == ENTRY_BODY_SHA256,'Entry body differs from the saved source')
    meta = json.loads(members['raw/cb_listed.html.meta.json'])
    require(meta['sha256'] == digest(body) and meta['http_status'] == 200 and meta['exit_code'] == 0,
            'Entry transport/body mismatch')
    effective = meta['curl']['url_effective']
    result = inspect_html(body,effective)
    source_proofs = []
    needles = {
        'route': ['API_PATTERN="/www/{LANG}/{ACTION}"','docLang=document.documentElement.lang'],
        'scripts': ["const langDir = { 'zh': 'zh-tw', 'en': 'en-us', 'jp': 'ja-jp' }",
                    '_.apiOption   = opt.option?opt.pattern.replace',
                    "let argv = keys.map(s=>'name='+s).join('&');",'$.get(_.apiOption,argv',
                    "oData['response'] = 'json';",'$.post(_.apiAction,oData',
                    'let op = new Option(o.text,o.value);','initForm(()=>{'],
    }
    for batch,(archive_sha,member,body_sha) in OLD_SOURCES.items():
        old,info = _saved(root,OLD_OUT,batch,archive_sha)
        raw = old[member]
        require(digest(raw) == body_sha,'Archived API-template script drift')
        evidence = []
        for literal in needles[batch]:
            offset = raw.find(literal.encode('utf-8'))
            require(offset >= 0,'Archived API-template declaration absent')
            evidence.append(dict(exact_literal=literal,byte_offset=offset,line=raw[:offset].count(b'\n')+1))
        source_proofs.append(dict(archive=info,member=member,body_sha256=body_sha,declarations=evidence))
    result.update(source_archive=archive,source_transport=dict(request=meta['request'],
                  request_started_at_utc=meta['request_started_at'],observed_at_utc=meta['observed_at'],
                  effective_url=effective,http_status=meta['http_status'],exit_code=meta['exit_code']),
                  archived_api_template_evidence=source_proofs,
                  next_same_origin_source=dict(url='https://www.tpex.org.tw/www/zh-tw/api/tpexList?name=bondIssuer',
                      method='GET',query=[dict(name='name',value='bondIssuer')],
                      meaning='Declared option route from the entry plus already archived main/tables templates; freeze separately before any request.',
                      followup_authorized=False),
                  report_route=dict(url='https://www.tpex.org.tw/www/zh-tw/bond/convSearch',method='POST',
                      known_fields=dict(name='bondIssuer',response='json'),searchNo_value=None,
                      reason='Options are appended in response order before autoLoad. Obtain actual option values/defaults before submitting a report; no issuer code is guessed.',
                      followup_authorized=False),
                  coverage_limits=['The entry is an interface, not a returned bond/contract data table.',
                      'All href/src/action occurrences remain, including unrelated navigation and foreign hosts.',
                      'The recently-listed report is not proven to cover the original29 put-calendar population.',
                      'The inline e[4] dynamic link formatter does not establish the unseen column schema or that its links are holder-put contracts.',
                      'No JS execution, request, current issuer selection, first-availability or cash-claim gate pass.'])
    return result


def options_inventory(root: Path | str = '.') -> dict:
    root = Path(root)
    entry = inventory(root)  # Replays the saved HTML and old static declarations.
    members,archive = _saved(root,OUT,'options',OPTIONS_SHA256)
    body = members['raw/bond_issuer_options.json']
    require(digest(body) == OPTIONS_BODY_SHA256,'Saved issuer option body drift')
    meta = json.loads(members['raw/bond_issuer_options.json.meta.json'])
    require(meta['sha256'] == digest(body) and meta['http_status'] == 200 and meta['exit_code'] == 0,
            'Option transport/body mismatch')
    result = inspect_options(body)
    forms = [form for form in entry['forms'] if dict(form['attributes']).get('id') == 'tables-form']
    require(len(forms) == 1,'Missing/ambiguous report form')
    selects = [control for control in forms[0]['controls'] if control['tag'] == 'select']
    require(len(selects) == 1 and selects[0]['name'] == 'searchNo' and not selects[0]['options']
            and 'multiple' not in dict(selects[0]['attributes']), 'Unexpected initial issuer selector')
    require(result['first_returned_option'] == {'value':'','text':'全部發行機構'},'Initial all-issuer option changed')
    fields = [('name','bondIssuer'),('searchNo',result['first_returned_option']['value']),('response','json')]
    result.update(source_archive=archive,source_member='raw/bond_issuer_options.json',
                  observed_at_utc=meta['observed_at'],source_entry_archive=entry['source_archive'],
                  archived_api_template_evidence=entry['archived_api_template_evidence'],
                  initial_ui_selection=result['first_returned_option'],
                  source_selection_rule='The single empty select receives new Option(text,value) in returned order before autoLoad; serializeObject retains the empty first value.',
                  issuer9958_actual_option=next((item for item in result['options'] if item['value'] == '9958'),None),
                  full_report_request=dict(url='https://www.tpex.org.tw/www/zh-tw/bond/convSearch',method='POST',
                      fields=[dict(name=name,value=value) for name,value in fields],data=urlencode(fields),
                      followup_authorized=False),
                  coverage_limits=['Issuer dropdown membership is not an outstanding-bond population or proof of the frozen29put-case coverage.',
                      'All310 returned options remain saved in source order; no recent issuer/profit filter is applied.',
                      'Option9958 exists in the response, but an issuer-specific report is distinct from the initial all-issuer request.'])
    return result


def report_inventory(root: Path | str = '.') -> dict:
    root = Path(root)
    options = options_inventory(root)
    members,archive = _saved(root,OUT,'report',REPORT_SHA256)
    member = 'raw/all_issuer_report.json'
    body = members[member]
    require(digest(body) == REPORT_BODY_SHA256,'Saved all-issuer report body drift')
    meta = _strict_json(members[member+'.meta.json'])
    expected_request = options['full_report_request']
    require(meta['sha256'] == digest(body) and meta['http_status'] == 200 and meta['exit_code'] == 0,
            'Report transport/body mismatch')
    require(all(meta['request'].get(key) == expected_request[key] for key in ('url','method','data'))
            and meta['curl']['url_effective'] == expected_request['url'], 'Report request differs from frozen all-issuer UI default')
    observed = datetime.fromisoformat(meta['observed_at'])
    started = datetime.fromisoformat(meta['request_started_at'])
    require(observed.tzinfo is not None and started.tzinfo is not None and started <= observed,
            'Report source timestamps invalid')
    full = inspect_report(body,meta['curl']['url_effective'])
    selection_body = (root/OUT/'selection.json').read_bytes()
    require(digest(selection_body) == SELECTION_SHA256,'Frozen29/control selection SHA mismatch')
    selection = _strict_json(selection_body)
    calendar_members,calendar_archive = _saved(root,OLD_OUT,'calendar',CALENDAR_SHA256)
    calendar_member = 'raw/put_20261020_20270420.json'
    calendar_body = calendar_members[calendar_member]
    require(digest(calendar_body) == CALENDAR_BODY_SHA256,'Original29 calendar body drift')
    calendar = _strict_json(calendar_body)
    require(calendar['stat'] == 'ok' and len(calendar['tables']) == 1,'Original calendar response invalid')
    original = calendar['tables'][0]
    require(selection['calendar_archive_sha256'] == CALENDAR_SHA256
            and selection['calendar_member'] == calendar_member
            and selection['calendar_member_sha256'] == CALENDAR_BODY_SHA256
            and selection['original_calendar_population_count'] == original['totalCount'] == len(original['data']) == 29
            and selection['original_calendar_fields'] == original['fields']
            and selection['original_calendar_rows'] == original['data'],
            'Frozen selection differs from full original29 calendar')
    original_codes = [row[0] for row in original['data']]
    require(len(set(original_codes)) == 29,'Duplicate original calendar bond code')
    by_bond = {row['bond_code']:row for row in full['rows']}
    coverage = []
    for number,row in enumerate(original['data'],1):
        found = by_bond.get(row[0])
        coverage.append(dict(original_calendar_row_number=number,bond_code=row[0],
                             original_calendar_row_sha256=_row_digest(row),
                             matched_exact_bond_id=found is not None,
                             report_row_number=found['row_number'] if found else None,
                             report_row_sha256=found['row_sha256'] if found else None,
                             issuance_data_pointer=found['issuance_data_pointer'] if found else None))
    controls = selection['controls_bond_codes']
    require(controls == ['99587','68351','68741'],'Frozen control identity changed')
    control_matches = []
    for bond in controls:
        found = by_bond.get(bond)
        control_matches.append(dict(bond_code=bond,matched_exact_bond_id=found is not None,
            report_row_number=found['row_number'] if found else None,
            original_report_fields=found['original_fields'] if found else None,
            row_sha256=found['row_sha256'] if found else None,
            issuance_data_pointer=found['issuance_data_pointer'] if found else None))
    source = dict(source_archive=archive,source_member=member,body_sha256=digest(body),
                  request=meta['request'],effective_url=meta['curl']['url_effective'],
                  request_started_at_utc=started.astimezone(timezone.utc).isoformat(),
                  observed_at_utc=observed.astimezone(timezone.utc).isoformat(),
                  observed_at_taipei=observed.astimezone(ZoneInfo('Asia/Taipei')).isoformat(),
                  http_status=meta['http_status'],exit_code=meta['exit_code'])
    full.update(source=source,all_source_rows_preserved=True)
    full_path = Path('inputs/frontier_cb_contract_20261022/report_full.json')
    encoded = (json.dumps(full,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (root/full_path).parent.mkdir(parents=True,exist_ok=True)
    (root/full_path).write_bytes(encoded)
    return dict(status='all_cb_report_rows_replayed_and_frozen29_exact_id_compared',
                source=source,fields=full['fields'],title=full['title'],reported_date_label=full['date'],
                declared_total=full['declared_total'],returned_row_count=full['returned_row_count'],
                count_reconciliation_passed=full['count_reconciliation_passed'],
                full_inventory=dict(path=str(full_path),sha256=digest(encoded),all_original_fields_retained=True),
                row_hashes=[dict(row_number=row['row_number'],bond_code=row['bond_code'],row_sha256=row['row_sha256'])
                            for row in full['rows']],
                frozen_calendar=dict(archive=calendar_archive,member=calendar_member,body_sha256=CALENDAR_BODY_SHA256,
                                     selection_sha256=SELECTION_SHA256,original_count=29),
                original29_coverage=coverage,original29_exact_match_count=sum(row['matched_exact_bond_id'] for row in coverage),
                original29_missing_bond_codes=[row['bond_code'] for row in coverage if not row['matched_exact_bond_id']],
                controls=control_matches,subtitle_original=full['subtitle_original'],
                subtitle_pointers=full['subtitle_pointers'],
                next_source_types='Actual issuance-data HTML interface links, plus subtitle MOPS query interface and instruction pointer; contents not fetched or qualified here.',
                UI_and_options_observed_at_utc=options['observed_at_utc'],
                coverage_limits=['totalCount reconciles this one current-vintage report response, not an independently complete bond population.',
                    'The full frozen29 calendar is compared by exact URL bond_id; an issuer-prefix match is not accepted.',
                    'Matched issuance-data links are not yet inspected documents, PDFs, application windows, payment calendars or verified holder-put contracts.',
                    'Oct22 UI/options and Oct23 report observations are distinct; reported dates are not historical first-availability evidence.',
                    'No URL was requested, JS executed, return scanned, or cash-claim/source/PIT gate promoted by this replay.'],
                complete_bond_population_verified=False,holder_put_contracts_verified=False,
                cash_claim_source_gate_passed=False,source_gate_passed=False,historical_pit_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root',default='.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--options',action='store_true')
    mode.add_argument('--report',action='store_true')
    parser.add_argument('--output',default=None)
    args = parser.parse_args()
    result = report_inventory(args.root) if args.report else options_inventory(args.root) if args.options else inventory(args.root)
    path = Path(args.output) if args.output else OUT/('report_inventory.json' if args.report else 'options_inventory.json' if args.options else 'entry_inventory.json')
    if not path.is_absolute():path = Path(args.root)/path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    counts = dict(returned_row_count=result['returned_row_count'],original29_exact_match_count=result['original29_exact_match_count']) if args.report else dict(returned_option_count=result['returned_option_count']) if args.options else dict(
        pointers=len(result['pointers']),forms=len(result['forms']),scripts=len(result['scripts']))
    print(json.dumps(dict(status=result['status'],**counts,source_gate_passed=False),ensure_ascii=False))

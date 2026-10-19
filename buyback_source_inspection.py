"""Describe saved public-source responses without promoting them to research data.

No network requests or JavaScript execution occur here. Literal routes are evidence
only: even a same-origin form/action does not authorize a follow-up request.
"""
import codecs
import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import re
from urllib.parse import urljoin, urlsplit


def _origin(url):
    try:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            return None
        return p.scheme.lower(), p.hostname.lower(), p.port or (443 if p.scheme == 'https' else 80)
    except ValueError:
        return None


def _route(raw, base, effective_url):
    """Preserve the observed literal alongside the conservative URL resolution."""
    url = urljoin(base, raw) if not any(ord(c) < 32 for c in raw) else None
    same = bool(url and _origin(url) and _origin(url) == _origin(effective_url))
    return dict(raw=raw, resolved_url=url, same_origin=same,
                evidence_only=True, followup_authorized=False)


class _Interface(HTMLParser):
    def __init__(self):
        # Text character references stay as written. HTMLParser decodes attribute
        # references itself, so raw start tags are also retained for audit.
        super().__init__(convert_charrefs=False)
        self.forms, self.scripts, self.inline_scripts, self.tables = [], [], [], []
        self.form = self.select = self.option = self.label = None
        self.script = None
        self.script_depth = self.style_depth = self.select_depth = 0
        self.table_stack = []
        self.visible, self.titles, self.title = [], [], None
        self.base_href = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        raw = self.get_starttag_text()
        if tag == 'base' and self.base_href is None and 'href' in a:
            self.base_href = a['href']
        if tag == 'script':
            self.script_depth += 1
            self.script = []
            if 'src' in a:
                self.scripts.append(dict(src=a['src'], raw_start_tag=raw))
            return
        if tag == 'style':
            self.style_depth += 1
        if tag == 'title':
            self.title = []
        if tag == 'form':
            self.form = dict(action_raw=a.get('action', ''), method_raw=a.get('method'),
                             method=(a.get('method') or 'get').lower(),
                             raw_start_tag=raw, hidden_inputs=[], selects=[], labels=[], text=[])
            self.forms.append(self.form)
        if tag == 'input' and self.form is not None and a.get('type', '').lower() == 'hidden':
            self.form['hidden_inputs'].append(dict(name=a.get('name'), value=a.get('value', ''),
                                                  raw_start_tag=raw))
        if tag == 'select':
            self.select_depth += 1
            if self.form is not None:
                self.select = dict(name=a.get('name'), raw_start_tag=raw, options=[])
                self.form['selects'].append(self.select)
        if tag == 'option' and self.select is not None:
            self.option = dict(value=a.get('value'), selected='selected' in a,
                               disabled='disabled' in a, text=[], raw_start_tag=raw)
            self.select['options'].append(self.option)
        if tag == 'label' and self.form is not None:
            self.label = dict(for_id=a.get('for'), text=[], raw_start_tag=raw)
            self.form['labels'].append(self.label)
        if tag == 'table':
            table = dict(header_cells=0, plain_data_rows=0, mixed_control_data_rows=0, rows=0)
            self.tables.append(table)
            self.table_stack.append(dict(table=table, row=None, cell=None))
        if self.table_stack:
            t = self.table_stack[-1]
            if tag == 'tr':
                t['row'] = dict(nonempty_td=False, interactive=False, plain_cells=0)
                t['table']['rows'] += 1
            if tag in ('td', 'th'):
                t['cell'] = dict(kind=tag, text=[], interactive=False)
                if tag == 'th':
                    t['table']['header_cells'] += 1
            if tag in ('input', 'select', 'button', 'textarea') and t['row'] is not None:
                t['row']['interactive'] = True
                if t['cell'] is not None:
                    t['cell']['interactive'] = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ('input', 'base', 'br', 'meta', 'link', 'img', 'hr'):
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.script_depth:
            self.script.append(data)
            return
        if self.style_depth:
            return
        self.visible.append(data)
        if self.title is not None:
            self.title.append(data)
        if self.form is not None:
            self.form['text'].append(data)
        if self.option is not None:
            self.option['text'].append(data)
        if self.label is not None:
            self.label['text'].append(data)
        if self.table_stack and self.table_stack[-1]['cell'] is not None and not self.select_depth:
            self.table_stack[-1]['cell']['text'].append(data)

    def handle_entityref(self, name):
        self.handle_data('&' + name + ';')

    def handle_charref(self, name):
        self.handle_data('&#' + name + ';')

    def handle_endtag(self, tag):
        if tag == 'script':
            if self.script is not None:
                self.inline_scripts.append(''.join(self.script))
            self.script, self.script_depth = None, max(0, self.script_depth - 1)
            return
        if tag == 'style':
            self.style_depth = max(0, self.style_depth - 1)
        if tag == 'title' and self.title is not None:
            self.titles.append(''.join(self.title))
            self.title = None
        if tag == 'form':
            self.form = self.select = self.option = self.label = None
        if tag == 'select':
            self.select_depth = max(0, self.select_depth - 1)
            self.select = self.option = None
        if tag == 'option':
            self.option = None
        if tag == 'label':
            self.label = None
        if self.table_stack:
            t = self.table_stack[-1]
            if tag in ('td', 'th') and t['cell'] is not None:
                c = t['cell']
                if c['kind'] == 'td' and ''.join(c['text']).strip() and t['row'] is not None:
                    t['row']['nonempty_td'] = True
                    if not c['interactive']:
                        t['row']['plain_cells'] += 1
                t['cell'] = None
            if tag == 'tr' and t['row'] is not None:
                if t['row']['nonempty_td'] and not t['row']['interactive']:
                    t['table']['plain_data_rows'] += 1
                elif t['row']['plain_cells'] >= 2:
                    # A result row can retain multiple ordinary data cells plus
                    # a separate detail/query button. Do not reject that whole
                    # row merely because the last cell is interactive. A lone
                    # query label next to an input is still insufficient.
                    t['table']['mixed_control_data_rows'] += 1
                t['row'] = None
            if tag == 'table':
                self.table_stack.pop()


_CHARSET = re.compile(br'<meta\b[^>]*\bcharset\s*=\s*["\']?\s*([A-Za-z0-9._-]+)', re.I)
_ERROR = re.compile(
    r'安全性問題|查詢過量|系統忙碌|系統發生錯誤|存取被拒|拒絕存取|網頁發生錯誤|'
    r'the requested url was rejected|access denied|request rejected|service unavailable|'
    r'403 forbidden|404 not found|internal server error', re.I)
_LITERAL_CALLS = [
    ('fetch', re.compile(r'\bfetch\s*\(\s*([\'\"])([^\'\"\r\n]+)\1\s*[,)]')),
    ('jquery_get_post', re.compile(r'(?:\$|jQuery)\s*\.\s*(?:get|post)\s*\(\s*([\'\"])([^\'\"\r\n]+)\1\s*[,)]')),
    ('jquery_ajax_url', re.compile(r'(?:\$|jQuery)\s*\.\s*ajax\s*\(\s*\{(?:(?!\}\s*\)).)*?\burl\s*:\s*([\'\"])([^\'\"\r\n]+)\1\s*[,}]', re.S)),
    ('xhr_open', re.compile(r'\b\w+\s*\.\s*open\s*\(\s*[\'\"](?:GET|POST)[\'\"]\s*,\s*([\'\"])([^\'\"\r\n]+)\1\s*[,)]', re.I)),
]


def inspect_response(body, effective_url, http_status, exit_code, expected_kind):
    """Return a JSON-safe description of captured bytes and transport metadata.

    ``expected_kind`` records the caller's intent, never validates a response's
    schema. A ``csv`` kind permits conservative structural CSV recognition.
    Invalid/unknown text encodings fail closed; replacement decoding is forbidden.
    """
    if not isinstance(body, bytes):
        raise TypeError('body must be the original bytes, not a decoded string')
    if not isinstance(effective_url, str) or not isinstance(expected_kind, str) or not expected_kind:
        raise ValueError('effective_url and a nonempty expected_kind must be strings')
    result = dict(classification='unrecognized', status='unrecognized', expected_kind=expected_kind,
                  effective_url=effective_url, http_status=http_status, exit_code=exit_code,
                  body_sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body), forms=[],
                  script_sources=[], ajax_routes=[], rejected_ajax_routes=[], tables=[],
                  historical_pit_verified=False, source_gate_passed=False,
                  complete_cohort_verified=False, empty_universe_verified=False,
                  site_blocking_proven=False, followup_authorized=False)
    try:
        status = int(http_status) if http_status is not None else 0
    except (ValueError, TypeError):
        status = 0
    transport_bad = exit_code != 0 or not 100 <= status <= 599
    if body.startswith(b'\xef\xbb\xbf'):
        encoding = 'utf-8-sig'
    else:
        meta = _CHARSET.search(body[:8192])
        encoding = meta[1].decode('ascii') if meta else 'utf-8'
    try:
        codecs.lookup(encoding)
        text = body.decode(encoding, errors='strict')
        result['decoding'] = dict(encoding=encoding, strict=True, error=None)
    except (UnicodeError, LookupError) as error:
        result['decoding'] = dict(encoding=encoding, strict=True, error=str(error))
        classification = 'transport_failure' if transport_bad else ('explicit_error_page' if status >= 400 else 'unrecognized')
        result.update(classification=classification, status=classification)
        return result
    if expected_kind.lower() in ('javascript', 'js', 'application/javascript', 'text/javascript'):
        # A saved script can contain HTML templates and error-message strings.
        # They are program text, not visible response-page evidence. Standalone
        # scripts are intentionally not parsed or executed by this inspector.
        classification = 'transport_failure' if transport_bad else ('explicit_error_page' if status >= 400 else 'unrecognized')
        result.update(classification=classification, status=classification,
                      content_interpretation='standalone_javascript_not_interpreted')
        return result
    parser = _Interface()
    parser.feed(text)
    parser.close()
    base = urljoin(effective_url, parser.base_href) if parser.base_href is not None else effective_url
    result['base_href_raw'], result['document_base_url'] = parser.base_href, base
    result['titles'] = parser.titles
    for form in parser.forms:
        form['action'] = _route(form['action_raw'], base, effective_url)
        form['text'] = ''.join(form['text'])
        for select in form['selects']:
            for option in select['options']:
                option['text'] = ''.join(option['text'])
        for label in form['labels']:
            label['text'] = ''.join(label['text'])
    result['forms'], result['tables'] = parser.forms, parser.tables
    result['script_sources'] = [dict(s, route=_route(s['src'], base, effective_url)) for s in parser.scripts]
    seen = set()
    for script in parser.inline_scripts:
        for kind, pattern in _LITERAL_CALLS:
            for match in pattern.finditer(script):
                literal = match[2]
                if (kind, literal) in seen:
                    continue
                seen.add((kind, literal))
                route = dict(_route(literal, base, effective_url), syntax=kind,
                             source_snippet=match[0])
                result['ajax_routes' if route['same_origin'] else 'rejected_ajax_routes'].append(route)
    visible = ''.join(parser.visible)
    error_match = _ERROR.search(visible)
    path_error = bool(re.search(r'/error/(?:error\.)?', urlsplit(effective_url).path, re.I))
    result['explicit_error_evidence'] = error_match[0] if error_match else None
    result['error_url_observed'] = path_error
    data_shape = None
    if any(t['header_cells'] and (t['plain_data_rows'] or t['mixed_control_data_rows'])
           and t['rows'] >= 2 for t in parser.tables):
        data_shape = 'html_table_structure_only'
    if text.lstrip().startswith(('{', '[')):
        try:
            json.loads(text)
            data_shape = 'json_syntax_only'
        except (ValueError, RecursionError):
            pass
    if 'csv' in expected_kind.lower():
        try:
            rows = list(csv.reader(io.StringIO(text)))
            if len(rows) >= 2 and len(rows[0]) >= 2 and all(len(r) == len(rows[0]) for r in rows):
                data_shape = 'csv_structure_only'
        except csv.Error:
            pass
    empty_claim = bool(re.search(r'查無資料|查無符合條件|no records found|no data found', visible, re.I))
    result['empty_result_claim_observed'] = empty_claim
    result['data_shape_observed'] = data_shape
    if transport_bad:
        classification = 'transport_failure'
    elif status >= 400 or path_error or error_match:
        classification = 'explicit_error_page'
    elif data_shape or empty_claim:
        classification = 'data_response_unverified'
    elif parser.forms or parser.scripts or '<html' in text.lower() and not parser.tables:
        classification = 'query_form_only'
    else:
        classification = 'unrecognized'
    result.update(classification=classification, status=classification)
    return result

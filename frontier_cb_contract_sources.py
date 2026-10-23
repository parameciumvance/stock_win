"""A separate bounded CB contract route; reuse immutable byte acquisition.

Only the saved TPEx literal entry anchor is executable in this initial batch.
Later batches need separately frozen, readback-bound literal link evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
import zipfile

from lxml import html

import frontier_sources

ROOT = Path('inputs/frontier_cb_contract_20261022')
OUT = Path('deliverables/frontier_cb_contract_20261022')
POLICY = Path('configs/frontier_cb_contract_protocol_20261022.json')
OFFICIAL_HOSTS = {'www.tpex.org.tw', 'mops.twse.com.tw', 'mopsov.twse.com.tw', 'doc.twse.com.tw'}


def require(value, message):
    if not value:
        raise ValueError(message)


def verify_literal_links(body, source_url, requests, *, label=None, tag='a', attribute='href'):
    """No URL construction beyond the official page's literal relative links."""
    require(tag in {'a', 'script'} and attribute == ('href' if tag == 'a' else 'src'),
            'Unsupported link evidence type')
    for url in [source_url] + [item['url'] for item in requests]:
        parts = urlsplit(url)
        require(parts.scheme == 'https' and parts.hostname in OFFICIAL_HOSTS
                and not parts.username and not parts.password, 'Link source/target is not an official HTTPS host')
    tree = html.fromstring(body, parser=html.HTMLParser(encoding='utf-8'))
    require(not tree.xpath('//base[@href]'), 'HTML base URL needs separate explicit lineage review')
    links = []
    for node in tree.xpath('//'+tag+'[@'+attribute+']'):
        text = ''.join(node.itertext()).strip()
        if label is None or text == label:
            links.append(urljoin(source_url, node.get(attribute)))
    require(requests and all(item.get('method', 'GET') == 'GET' and not item.get('data')
                            and item['url'] in links for item in requests),
            'Request lacks the saved literal link evidence')


def verified_evidence(spec):
    package = json.loads(Path(spec['package_path']).read_text())
    transfer = json.loads(Path(package['transfer_receipt']).read_text())
    require(package['sha256'] == transfer['sha256'] == spec['archive_sha256']
            and transfer.get('roundtrip_verified') is True, 'Link source readback absent or drifted')
    body = Path(package['retrieved']).read_bytes()
    require(hashlib.sha256(body).hexdigest() == spec['archive_sha256'], 'Link archive SHA drift')
    with zipfile.ZipFile(Path(package['retrieved'])) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read('manifest.json'))
        require(len(names) == len(set(names)) and archive.testzip() is None
                and set(names) == set(manifest) | {'manifest.json'}, 'Link archive CRC/population drift')
        for name, expected in manifest.items():
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected,
                    'Link archive inner SHA drift')
        require(package['manifest_files'] == len(manifest), 'Link manifest count drift')
        body = archive.read(spec['member'])
        require(hashlib.sha256(body).hexdigest() == spec['body_sha256'], 'Link page SHA drift')
        meta = json.loads(archive.read(spec['member']+'.meta.json'))
        require(meta.get('http_status') == 200 and meta.get('exit_code') == 0
                and meta['request']['url'] == spec['source_url']
                and meta['sha256'] == spec['body_sha256'], 'Link page transport/identity drift')
    return body


def verify_cb_option_template(entry, main, tables, requests):
    """One exact source-declared option GET; no report values are inferred."""
    tree = html.fromstring(entry, parser=html.HTMLParser(encoding='utf-8'))
    require(not tree.xpath('//base[@href]'), 'HTML base URL needs separate explicit lineage review')
    require(re.match(r'^zh', tree.get('lang', ''), re.I), 'Entry does not declare the verified Chinese language')
    entry_url = 'https://www.tpex.org.tw/zh-tw/bond/issue/cbond/listed.html'
    scripts = [urljoin(entry_url, value) for value in tree.xpath('//script/@src')]
    require('https://www.tpex.org.tw/rsrc/js/main.js' in scripts
            and 'https://www.tpex.org.tw/rsrc/js/tables.js' in scripts,
            'Entry lacks its archived API template scripts')
    calls = [text for text in tree.xpath('//script[not(@src)]/text()') if 'tables.init(' in text]
    require(len(calls) == 1 and len(re.findall(r'tables\.init\(', calls[0])) == 1
            and re.search(r'tables\.init\(\{\s*pattern\s*:\s*API_PATTERN\s*,\s*action\s*:\s*"bond/convSearch"\s*,\s*option\s*:\s*"api/tpexList"\s*,', calls[0]),
            'Entry API action/option declarations differ from the reviewed template')
    forms = tree.xpath('//form[@id="tables-form"]')
    require(len(forms) == 1, 'Missing/duplicate CB report form')
    form = forms[0]
    require(form.get('action') is None and form.get('method') is None
            and [(node.get('type'), node.get('name'), node.get('value')) for node in form.xpath('.//input')]
                == [('hidden', 'name', 'bondIssuer')], 'CB form hidden fields/action changed')
    selects = form.xpath('.//select')
    require(len(selects) == 1 and selects[0].get('name') == 'searchNo'
            and selects[0].get('data-option') == 'bondIssuer'
            and selects[0].get('value') is None and not selects[0].xpath('.//option'),
            'CB issuer option declaration/default changed; no searchNo value may be guessed')
    main_text, tables_text = main.decode('utf-8'), tables.decode('utf-8')
    require(len(re.findall(r'API_PATTERN\s*=\s*"/www/\{LANG\}/\{ACTION\}"', main_text)) == 1,
            'Archived API_PATTERN declaration missing/ambiguous')
    required = [
        "const docLang = document.documentElement.lang;",
        "_.#lan = /^zh/i.test(docLang)?'zh':(/jp/i.test(docLang)?'jp':'en');",
        "const langDir = { 'zh': 'zh-tw', 'en': 'en-us', 'jp': 'ja-jp' }",
        "_.apiOption   = opt.option?opt.pattern.replace(/\\{LANG\\}/,langDir[_.#lan]).replace(/\\{ACTION\\}/,opt.option):'';",
        "let keys = [...$('select[data-option]',$form)].map(el=>$(el).data('option'));",
        "let argv = keys.map(s=>'name='+s).join('&');",
        "$.get(_.apiOption,argv,(J)=>{",
    ]
    require(all(fragment in tables_text for fragment in required),
            'Archived option language/template/query/GET declarations differ')
    path = '/www/{LANG}/{ACTION}'.replace('{LANG}', 'zh-tw').replace('{ACTION}', 'api/tpexList')
    expected_url = 'https://www.tpex.org.tw'+path+'?name=bondIssuer'
    require(len(requests) == 1 and requests[0]['url'] == expected_url
            and requests[0].get('method', 'GET') == 'GET' and 'data' not in requests[0],
            'Request differs from exact declared issuer-options GET/query')
    return dict(method='GET', url=expected_url, query_fields=[['name', 'bondIssuer']],
                report_action='bond/convSearch', report_request_authorized=False,
                searchNo_value_inferred=False)


def verify_cb_report_template(entry, main, tables, options, requests):
    """Reproduce only the initial all-issuer form POST from saved option values."""
    option_url = 'https://www.tpex.org.tw/www/zh-tw/api/tpexList?name=bondIssuer'
    verify_cb_option_template(entry, main, tables, [dict(url=option_url)])
    tree = html.fromstring(entry, parser=html.HTMLParser(encoding='utf-8'))
    form = tree.xpath('//form[@id="tables-form"]')[0]
    controls = form.xpath('.//*[@name]')
    require([(node.tag, dict(node.attrib)) for node in controls] == [
        ('input', dict(type='hidden', name='name', value='bondIssuer')),
        ('select', {'name': 'searchNo', 'data-option': 'bondIssuer'})],
        'Report named controls/order/data overrides differ from the reviewed initial form')
    init = next(text for text in tree.xpath('//script[not(@src)]/text()') if 'tables.init(' in text)
    require('autoLoad:!0' in init and 'serverPaging' not in init and 'pagin:0' in init,
            'Report initial loading/server-paging declarations changed')
    main_text, table_text = main.decode('utf-8'), tables.decode('utf-8')
    require('$.fn.serializeObject=function(){var t={};return $.each(this.serializeArray(),(function(e,n){var r=t[n.name];null!=r?Array.isArray(r)?r.push(n.value):t[n.name]=[r,n.value]:t[n.name]=n.value})),t}' in main_text,
            'Saved form serializer does not establish preservation of empty option values')
    required = [
        "_.apiAction   = opt.action?opt.pattern.replace(/\\{LANG\\}/,langDir[_.#lan]).replace(/\\{ACTION\\}/,opt.action):'';",
        'for(let o of J.options[key]) {', 'let op = new Option(o.text,o.value);', '$select[0].add(op);',
        'let o = _.#$.form.serializeObject();',
        '_.#formData = _.#getFromSerializeObject();',
        'let oData = Object.assign({},_.#formData);', "oData['response'] = 'json';",
        "serverPaging: false,", "$.post(_.apiAction,oData, _.#renderReports.bind(_) ,'json');",
    ]
    require(all(fragment in table_text for fragment in required),
            'Saved default option/serializer/report POST declarations differ')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate options JSON key')
            result[key] = value
        return result
    value = json.loads(options, object_pairs_hook=pairs)
    require(isinstance(value, dict) and set(value) == {'options', 'stat'} and value['stat'] == 'ok'
            and isinstance(value['options'], dict) and set(value['options']) == {'bondIssuer'},
            'Saved issuer-option response schema/status changed')
    rows = value['options']['bondIssuer']
    require(isinstance(rows, list) and rows and all(isinstance(row, dict) and set(row) == {'value', 'text'}
            and type(row['value']) is str and type(row['text']) is str for row in rows)
            and len({row['value'] for row in rows}) == len(rows), 'Issuer options have malformed/duplicate values')
    require(rows[0] == dict(value='', text='全部發行機構'),
            'Saved first option does not establish the initial all-issuer empty value')
    report_url = 'https://www.tpex.org.tw/www/zh-tw/bond/convSearch'
    data = 'name=bondIssuer&searchNo=&response=json'
    require(len(requests) == 1 and requests[0]['url'] == report_url
            and requests[0].get('method') == 'POST' and requests[0].get('data') == data,
            'Request differs from the exact initial all-issuer report POST/three fields')
    return dict(method='POST',url=report_url,data=data,form_fields=[['name','bondIssuer'],['searchNo',''],['response','json']],
                saved_options_count=len(rows),first_option=rows[0],issuer_filter_applied=False,
                complete_original_29_case_coverage_verified=False,contract_document_qualified=False)


def module():
    frontier_sources.ROOT, frontier_sources.OUT, frontier_sources.POLICY = ROOT, OUT, POLICY
    return frontier_sources


def plan(batch='entry'):
    shared = module()
    result = shared.plan(batch)
    policy = shared.read(POLICY)
    require(policy['max_saved_requests'] == 4 and policy['max_source_batches'] == 3
            and policy['workers'] == 2 and policy['automatic_retries'] == 0,
            'CB contract phase allocation drift')
    require(result[1]['allowed_hosts'] and set(result[1]['allowed_hosts']) <= OFFICIAL_HOSTS,
            'Source host allocation outside official CB route')
    selection = Path(policy['selection']['path'])
    require(shared.sha256(selection) == policy['selection']['sha256'], 'CB selection drift')
    value = shared.read(selection)
    require(value['controls_bond_codes'] == ['99587', '68351', '68741']
            and value['original_calendar_population_count'] == 29,
            'Chronological route controls/population drift')
    if batch == 'entry':
        spec = policy['entry_source_evidence']
    else:
        require(result[3] is not None, 'Adaptive batch lacks a separate freeze')
        freeze = shared.read(result[3])
        template = freeze.get('api_template_evidence')
        if template is not None:
            template_id = template.get('template_id')
            expected_sources = {'entry', 'main', 'tables'} | (
                {'options'} if template_id == 'tpex_cb_initial_all_issuer_report_v1' else set())
            require(template_id in {'tpex_cb_bond_issuer_options_v1', 'tpex_cb_initial_all_issuer_report_v1'}
                    and set(template.get('sources', {})) == expected_sources
                    and result[1]['requests'] == [template.get('request')],
                    'Unsupported/ambiguous CB API template freeze')
            bodies = {key: verified_evidence(value) for key, value in template['sources'].items()}
            if template_id == 'tpex_cb_bond_issuer_options_v1':
                verify_cb_option_template(bodies['entry'], bodies['main'], bodies['tables'], result[1]['requests'])
            else:
                proof = verify_cb_report_template(bodies['entry'], bodies['main'], bodies['tables'], bodies['options'], result[1]['requests'])
                require(proof['saved_options_count'] == 310, 'Reviewed saved issuer option population changed')
            return result
        spec = freeze.get('literal_link_evidence')
        require(isinstance(spec, dict), 'Adaptive batch lacks readback-bound literal link evidence')
    body = verified_evidence(spec)
    verify_literal_links(body, spec['source_url'], result[1]['requests'],
                         label=spec.get('anchor_label'), tag=spec.get('tag', 'a'),
                         attribute=spec.get('attribute', 'href'))
    return result


def execute(stage, batch='entry'):
    plan(batch)  # Complete lineage/budget/old-checkpoint checks before any source IO.
    getattr(module(), stage)(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['plan', 'acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='entry')
    arguments = parser.parse_args()
    if arguments.stage == 'plan':
        requests, cfg, _, _ = plan(arguments.batch)
        print(json.dumps(dict(batch=arguments.batch, requests_path=str(requests),
                              requests=len(cfg['requests']), source_io_performed=False)))
    else:
        execute(arguments.stage, arguments.batch)

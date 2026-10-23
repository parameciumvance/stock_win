"""Synthetic source-lineage failures are rejected before any native request."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import frontier_cb_contract_sources as source


def digest(body):
    return hashlib.sha256(body).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class ContractSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.original_shared_paths = source.frontier_sources.ROOT, source.frontier_sources.OUT, source.frontier_sources.POLICY
        self.root, self.out = Path('inputs/cb_fixture'), Path('deliverables/cb_fixture')
        self.policy_path = Path('configs/cb_fixture.json')
        self.patches = [patch.object(source, 'ROOT', self.root), patch.object(source, 'OUT', self.out),
                        patch.object(source, 'POLICY', self.policy_path),
                        patch.object(source.frontier_sources, 'native_acquire')]
        for item in self.patches:
            item.start()
        self.page = '<a href="./listed.html">最近上櫃轉(交)換公司債</a>'.encode()
        self.url = 'https://www.tpex.org.tw/zh-tw/bond/issue/cbond/option.html'
        self.request = dict(filename='listed.html', url='https://www.tpex.org.tw/zh-tw/bond/issue/cbond/listed.html')
        self.request_path = Path('configs/cb_entry.json')
        save(self.request_path, dict(output_directory=str(self.root/'raw_entry'),
                                    allowed_hosts=['www.tpex.org.tw'], requests=[self.request]))
        Path('old_frozen.txt').write_bytes(b'prior immutable data')
        save('prior.json', dict(files={'old_frozen.txt': digest(Path('old_frozen.txt').read_bytes())}))
        save(self.out/'selection.json', dict(controls_bond_codes=['99587','68351','68741'],
                                             original_calendar_population_count=29))
        self.spec = dict(package_path=str(self.out/'old_package.json'), member='raw/option.html',
                         source_url=self.url, body_sha256=digest(self.page),
                         anchor_label='最近上櫃轉(交)換公司債')
        self.archive()
        self.policy = dict(prior_checkpoints={'prior.json': digest(Path('prior.json').read_bytes())},
            max_saved_requests=4, max_source_batches=3, workers=2, automatic_retries=0,
            selection=dict(path=str(self.out/'selection.json'), sha256=digest((self.out/'selection.json').read_bytes())),
            entry_source_evidence=self.spec, batches=dict(entry=dict(path=str(self.request_path),
                sha256=digest(self.request_path.read_bytes()), requests=1)))
        self.freeze()

    def tearDown(self):
        source.frontier_sources.ROOT, source.frontier_sources.OUT, source.frontier_sources.POLICY = self.original_shared_paths
        for item in reversed(self.patches):
            item.stop()
        os.chdir(self.cwd)
        self.temp.cleanup()

    def archive(self, *, wrong_inner=False, wrong_url=False):
        metadata = dict(request=dict(url=self.url if not wrong_url else 'https://www.tpex.org.tw/other'),
                        sha256=digest(self.page), http_status=200, exit_code=0)
        members = {'raw/option.html': self.page, 'raw/option.html.meta.json': json.dumps(metadata).encode()}
        manifest = {name: digest(body) for name, body in members.items()}
        if wrong_inner:
            manifest['raw/option.html'] = digest(b'different original')
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as zipped:
            for name, body in members.items():
                zipped.writestr(name, body)
            zipped.writestr('manifest.json', json.dumps(manifest))
        body = output.getvalue()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root/'prior.retrieved.zip').write_bytes(body)
        self.spec['archive_sha256'] = digest(body)
        save(self.root/'prior_transfer.json', dict(sha256=digest(body), roundtrip_verified=True))
        save(self.spec['package_path'], dict(sha256=digest(body), manifest_files=2,
            retrieved=str(self.root/'prior.retrieved.zip'), transfer_receipt=str(self.root/'prior_transfer.json')))

    def freeze(self):
        save(self.policy_path, self.policy)
        save(self.out/'protocol_freeze.json', dict(protocol_sha256=digest(self.policy_path.read_bytes())))

    def test_literal_saved_anchor_and_prior_bindings_allow_plan_only(self):
        request_path, cfg, _, _ = source.plan()
        self.assertEqual(request_path, self.request_path)
        self.assertEqual(cfg['requests'], [self.request])
        source.frontier_sources.native_acquire.assert_not_called()

    def test_guessed_pdf_and_changed_query_lack_literal_evidence(self):
        for url in ('https://www.tpex.org.tw/pdf/99587.pdf', self.request['url']+'?co_id=9958'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'literal link evidence'):
                source.verify_literal_links(self.page, self.url, [dict(filename='x.html',url=url)])

    def test_label_and_method_cannot_be_substituted(self):
        with self.assertRaisesRegex(ValueError, 'literal link evidence'):
            source.verify_literal_links(self.page, self.url, [self.request], label='公開說明書')
        with self.assertRaisesRegex(ValueError, 'literal link evidence'):
            source.verify_literal_links(self.page, self.url, [dict(self.request,method='POST',data='step=9')])

    def test_literal_external_link_cannot_become_an_official_source(self):
        body = b'<a href="https://example.com/contract.pdf">contract</a>'
        with self.assertRaisesRegex(ValueError, 'official HTTPS host'):
            source.verify_literal_links(body, self.url,
                [dict(filename='x.pdf',url='https://example.com/contract.pdf')])

    def test_rehashed_outer_archive_does_not_hide_changed_member(self):
        self.archive(wrong_inner=True)
        with self.assertRaisesRegex(ValueError, 'inner SHA drift'):
            source.verified_evidence(self.spec)

    def test_official_page_url_must_match_saved_transport_metadata(self):
        self.archive(wrong_url=True)
        with self.assertRaisesRegex(ValueError, 'transport/identity'):
            source.verified_evidence(self.spec)

    def test_old_checkpoint_drift_blocks_before_native_acquisition(self):
        Path('old_frozen.txt').write_bytes(b'new replacement')
        with self.assertRaisesRegex(ValueError, 'Prior checkpoint member drift'):
            source.execute('acquire')
        source.frontier_sources.native_acquire.assert_not_called()

    def test_phase_cap_cannot_silently_expand(self):
        self.policy['max_saved_requests'] = 6
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'allocation drift'):
            source.execute('acquire')
        source.frontier_sources.native_acquire.assert_not_called()

    def test_adaptive_batch_requires_its_own_readback_bound_link(self):
        save('configs/cb_next.json', dict(output_directory=str(self.root/'raw_next'),
                                        allowed_hosts=['www.tpex.org.tw'],requests=[self.request]))
        save(self.out/'next_freeze.json',dict(protocol_sha256=digest(self.policy_path.read_bytes()),
            path='configs/cb_next.json',sha256=digest(Path('configs/cb_next.json').read_bytes()),requests=1))
        with self.assertRaisesRegex(ValueError, 'readback-bound literal link'):
            source.execute('acquire', 'next')
        source.frontier_sources.native_acquire.assert_not_called()

    def test_fourth_batch_fails_even_when_four_request_cap_has_capacity(self):
        for batch in ('options','report','artifact'):
            save(self.out/(batch+'_freeze.json'),dict(protocol_sha256=digest(self.policy_path.read_bytes()),
                path=str(self.request_path),sha256=digest(self.request_path.read_bytes()),requests=1))
        with self.assertRaisesRegex(ValueError, 'budget exceeded'):
            source.execute('acquire', 'artifact')
        source.frontier_sources.native_acquire.assert_not_called()

    def test_report_template_cannot_skip_saved_options_evidence(self):
        save(self.out/'report_freeze.json',dict(protocol_sha256=digest(self.policy_path.read_bytes()),
            path=str(self.request_path),sha256=digest(self.request_path.read_bytes()),requests=1,
            api_template_evidence=dict(template_id='tpex_cb_initial_all_issuer_report_v1',
                request=self.request,sources=dict(entry=self.spec,main=self.spec,tables=self.spec))))
        with self.assertRaisesRegex(ValueError, 'Unsupported/ambiguous CB API template'):
            source.execute('acquire', 'report')
        source.frontier_sources.native_acquire.assert_not_called()


class DeclaredApiTemplateTests(unittest.TestCase):
    def setUp(self):
        self.entry = '''<html lang="zh-Hant-tw"><script src="/rsrc/js/main.js"></script>
            <script src="/rsrc/js/tables.js"></script><form id="tables-form">
            <input type="hidden" name="name" value="bondIssuer">
            <select name="searchNo" data-option="bondIssuer"></select></form>
            <script>tables.init({pattern:API_PATTERN,action:"bond/convSearch",option:"api/tpexList",autoLoad:!0});</script>
            </html>'''.encode()
        self.main = b'let API_PATTERN="/www/{LANG}/{ACTION}";'
        self.tables = '''const docLang = document.documentElement.lang;
_.#lan = /^zh/i.test(docLang)?'zh':(/jp/i.test(docLang)?'jp':'en');
const langDir = { 'zh': 'zh-tw', 'en': 'en-us', 'jp': 'ja-jp' }
_.apiOption   = opt.option?opt.pattern.replace(/\\{LANG\\}/,langDir[_.#lan]).replace(/\\{ACTION\\}/,opt.option):'';
let keys = [...$('select[data-option]',$form)].map(el=>$(el).data('option'));
let argv = keys.map(s=>'name='+s).join('&');
$.get(_.apiOption,argv,(J)=>{'''.encode()
        self.request = dict(filename='bond_issuer_options.json',method='GET',
            url='https://www.tpex.org.tw/www/zh-tw/api/tpexList?name=bondIssuer')

    def verify(self, request=None):
        return source.verify_cb_option_template(self.entry,self.main,self.tables,
                                                [request or self.request])

    def test_source_template_allows_only_options_and_no_report_or_search_value(self):
        result = self.verify()
        self.assertEqual(result['query_fields'], [['name','bondIssuer']])
        self.assertFalse(result['report_request_authorized'])
        self.assertFalse(result['searchNo_value_inferred'])

    def test_extra_or_guessed_query_duplicate_names_and_wrong_method_fail(self):
        for suffix in ('&searchNo=9958', '&response=json', '&name=bondIssuer', '#fragment'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'exact declared'):
                self.verify(dict(self.request,url=self.request['url']+suffix))
        for request in (dict(self.request,method='POST'),dict(self.request,data=''),
                        dict(self.request,url=self.request['url'].replace('zh-tw','en-us'))):
            with self.subTest(request=request), self.assertRaisesRegex(ValueError, 'exact declared'):
                self.verify(request)

    def test_report_action_or_option_path_change_is_rejected(self):
        original = self.entry
        for old,new in ((b'bond/convSearch',b'bond/other'),(b'api/tpexList',b'api/guessed')):
            self.entry = original.replace(old,new)
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, 'action/option'):
                self.verify()

    def test_no_report_default_can_be_invented_from_an_empty_select(self):
        for replacement in (b'<select name="searchNo" value="all" data-option="bondIssuer">',
                            b'<select name="searchNo" data-option="bondIssuer"><option value="all">all</option>'):
            original = self.entry
            self.entry = original.replace(b'<select name="searchNo" data-option="bondIssuer">',replacement)
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, 'default changed'):
                self.verify()
            self.entry = original

    def test_get_query_generation_and_language_map_must_be_saved_source_declarations(self):
        original = self.tables
        for old,new in ((b'$.get(',b'$.post('),(b"'zh': 'zh-tw'",b"'zh': 'en-us'"),
                        (b"s=>'name='+s",b"s=>'searchNo='+s")):
            self.tables = original.replace(old,new)
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, 'GET declarations'):
                self.verify()

    def test_missing_scripts_ambiguous_pattern_and_base_declaration_fail(self):
        self.main *= 2
        with self.assertRaisesRegex(ValueError, 'missing/ambiguous'):
            self.verify()
        self.main = self.main[:len(self.main)//2]
        self.entry = self.entry.replace(b'<html ',b'<base href="https://example.com/"><html ')
        with self.assertRaisesRegex(ValueError, 'base URL'):
            self.verify()

    def test_script_route_and_page_language_cannot_change(self):
        original = self.entry
        self.entry = original.replace(b'/rsrc/js/main.js',b'/rsrc/js/other.js')
        with self.assertRaisesRegex(ValueError, 'template scripts'):
            self.verify()
        self.entry = original.replace(b'zh-Hant-tw',b'en-us')
        with self.assertRaisesRegex(ValueError, 'Chinese language'):
            self.verify()


class InitialReportTemplateTests(unittest.TestCase):
    def setUp(self):
        base = DeclaredApiTemplateTests()
        base.setUp()
        self.entry = base.entry.replace(b'autoLoad:!0',b'autoLoad:!0,tables:[{pagin:0}]')
        self.main = base.main + b'''$.fn.serializeObject=function(){var t={};return $.each(this.serializeArray(),(function(e,n){var r=t[n.name];null!=r?Array.isArray(r)?r.push(n.value):t[n.name]=[r,n.value]:t[n.name]=n.value})),t}'''
        self.tables = base.tables + b'''
_.apiAction   = opt.action?opt.pattern.replace(/\\{LANG\\}/,langDir[_.#lan]).replace(/\\{ACTION\\}/,opt.action):'';
for(let o of J.options[key]) {
let op = new Option(o.text,o.value);
$select[0].add(op);
let o = _.#$.form.serializeObject();
_.#formData = _.#getFromSerializeObject();
let oData = Object.assign({},_.#formData);
oData['response'] = 'json';
serverPaging: false,
$.post(_.apiAction,oData, _.#renderReports.bind(_) ,'json');'''
        self.options = dict(stat='ok',options=dict(bondIssuer=[
            dict(value='',text='全部發行機構'),dict(value='9958',text='世紀鋼')]))
        self.request = dict(filename='all_issuer_report.json',url='https://www.tpex.org.tw/www/zh-tw/bond/convSearch',
                            method='POST',data='name=bondIssuer&searchNo=&response=json')

    def verify(self):
        return source.verify_cb_report_template(self.entry,self.main,self.tables,
            json.dumps(self.options,ensure_ascii=False).encode(),[self.request])

    def test_empty_first_option_and_serialization_support_only_initial_all_issuer_post(self):
        result = self.verify()
        self.assertEqual(result['form_fields'],[['name','bondIssuer'],['searchNo',''],['response','json']])
        self.assertFalse(result['issuer_filter_applied'])
        self.assertFalse(result['complete_original_29_case_coverage_verified'])
        self.assertFalse(result['contract_document_qualified'])

    def test_blank_is_not_inferred_if_source_first_option_changes(self):
        self.options['options']['bondIssuer'].reverse()
        with self.assertRaisesRegex(ValueError, 'initial all-issuer empty'):
            self.verify()

    def test_duplicate_option_values_or_nonstring_blank_are_rejected(self):
        self.options['options']['bondIssuer'].append(dict(value='',text='another all'))
        with self.assertRaisesRegex(ValueError, 'duplicate values'):
            self.verify()
        self.options['options']['bondIssuer'].pop()
        self.options['options']['bondIssuer'][0]['value'] = None
        with self.assertRaisesRegex(ValueError, 'malformed'):
            self.verify()

    def test_filter_default_guess_and_additional_fields_are_rejected(self):
        for data in ('name=bondIssuer&searchNo=9958&response=json',
                     'bondIssuer=&searchNo=&response=json',
                     'name=bondIssuer&searchNo=all&response=json',
                     'name=bondIssuer&searchNo=&response=json&date=20261022'):
            self.request['data'] = data
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'three fields'):
                self.verify()

    def test_serializer_that_drops_empty_values_or_uses_get_is_rejected(self):
        original_main,original_tables = self.main,self.tables
        self.main = original_main.replace(b't[n.name]=n.value',b't[n.name]=n.value||undefined')
        with self.assertRaisesRegex(ValueError, 'preservation of empty'):
            self.verify()
        self.main = original_main
        self.tables = original_tables.replace(b'$.post(_.apiAction',b'$.get(_.apiAction')
        with self.assertRaisesRegex(ValueError, 'report POST declarations'):
            self.verify()

    def test_hidden_data_override_and_reordered_controls_are_rejected(self):
        self.entry = self.entry.replace(b'name="searchNo"',b'name="searchNo" data-value="9958"')
        with self.assertRaisesRegex(ValueError, 'controls/order/data overrides'):
            self.verify()

    def test_server_paging_cannot_add_unreviewed_fields(self):
        self.entry = self.entry.replace(b'autoLoad:!0',b'autoLoad:!0,serverPaging:!0')
        with self.assertRaisesRegex(ValueError, 'server-paging'):
            self.verify()


if __name__ == '__main__':
    unittest.main()

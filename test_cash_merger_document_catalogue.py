"""Catalogue rows, cross-year returns and source-bound download parameters."""
import copy
import hashlib
from html import escape
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from cash_merger_document_catalogue import (
    DOWNLOAD_URL, FORM_FIELDS, HEADERS, parse_catalogue, validate_download_requests,
)
import merger_documents_sources as sources


def fixture():
    original = [
        ['6674', '114 年', '股東會相關資料', '\xa0', '常會', '年報', '\xa0', 'actual_older_A.pdf', '  123', '115/06/03 14:00:00', '無'],
        ['6674', '115 年', '股東會相關資料', '\xa0', '第一次臨時會', '議事手冊及會議補充資料', '\xa0',
         'actual_handbook_F02.pdf', '  1,187,933', '115/10/20 16:33:33', '無'],
        ['6674', '115 年', '股東會相關資料', '\xa0', '第一次臨時會', '股東會各項議案參考資料', '\xa0',
         'actual_reference_F13.pdf', '  190,821', '115/10/20 16:32:24', '無'],
        ['6674', '114 年', '股東會相關資料', '\xa0', '常會', '英文年報', '\xa0', 'actual_older_B.pdf', '  234', '115/06/03 14:01:00', '無'],
    ]
    fields = ''.join(f'<input name="{name}" value="{value}">' for name, value in FORM_FIELDS)
    rows = []
    for values in original:
        cells = []
        for column, value in enumerate(values):
            text = escape(value).replace('\xa0', '&nbsp;')
            if column == 7:
                text = f'<a href=\'javascript:readfile2("F","6674","{value}");\'>{text}</a>'
            cells.append('<td>' + text + '</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    script = '''function readfile2(kind,coid,filename){
 var f = document.forms[0]; if (true) { var text = "}"; }
 f.step.value = 9; f.kind.value = kind; f.co_id.value = coid;
 f.filename.value = filename; f.submit(); }
'''
    page = ('<html><meta charset="big5"><form name="fm2" action="/server-java/t57sb01" method="post">'
            + fields + '<table><tr>' + ''.join('<th>' + value + '</th>' for value in HEADERS) + '</tr>'
            + ''.join(rows) + '</table><form name="fm4"><input name="step" value="1">'
            + '<input name="co_id" value="6674"><input name="year" value="114"></form>'
            + '<script>' + script + '</script></html>')
    body, headers = page.encode('big5'), b'Content-Type: text/html;charset=big5\r\n'
    full, summary = parse_catalogue(body, headers)
    selection = dict(source_catalogue=dict(body_sha256=hashlib.sha256(body).hexdigest(), encoding='big5'),
                     meeting_label='第一次臨時會', meeting_date='2026-11-09', rows=[])
    requests = []
    for number in (2, 3):
        cells = original[number - 1]
        fields = dict(FORM_FIELDS, step='9', kind='F', co_id='6674', filename=cells[7])
        ordered = [(name, fields[name]) for name, _ in FORM_FIELDS]
        selected = dict(catalogue_row_number=number, original_cells=cells, source_filename=cells[7],
            new_filename=cells[7], document_type=cells[5], display_size_bytes=int(cells[8].replace(',', '')),
            declared_uploaded_at=cells[9], request_fields=[dict(name=name, value=value) for name, value in ordered])
        selection['rows'].append(selected)
        requests.append(dict(filename=cells[7], url=DOWNLOAD_URL, method='POST', data=urlencode(ordered)))
    return body, headers, full, summary, selection, dict(requests=requests)


class CatalogueTests(unittest.TestCase):
    def test_all_columns_padding_and_cross_year_rows_are_preserved(self):
        body, _, full, summary, selection, cfg = fixture()
        self.assertEqual(summary['catalogue_row_count'], 4)
        self.assertEqual(summary['returned_other_year_row_numbers'], [1, 4])
        self.assertEqual(full['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(full['catalogue_rows'][1]['original_cells'], selection['rows'][0]['original_cells'])
        self.assertEqual(full['catalogue_rows'][1]['original_cells'][8], '  1,187,933')
        self.assertEqual(full['catalogue_rows'][1]['original_cells'][3], '\xa0')
        self.assertFalse(summary['query_year_filter_reapplied'])
        self.assertFalse(summary['document_population_complete'])
        validate_download_requests(full, selection, cfg)

    def test_nested_fm4_fields_are_not_silently_added_to_fm2_download_request(self):
        _, _, full, _, selection, cfg = fixture()
        form = next(form for form in full['forms'] if form['attributes'].get('name') == 'fm2')
        self.assertEqual([(c['attributes']['name'], c['attributes'].get('value', '')) for c in form['controls']], FORM_FIELDS)
        validate_download_requests(full, selection, cfg)
        selection['rows'][0]['request_fields'].append(dict(name='year', value='114'))
        with self.assertRaisesRegex(ValueError, 'eleven'):
            validate_download_requests(full, selection, cfg)

    def test_row_or_filename_substitution_and_derived_metadata_changes_fail(self):
        for key, value in [('original_cells', []), ('source_filename', 'guessed.pdf'),
                           ('display_size_bytes', 1), ('declared_uploaded_at', '115/10/21 00:00:00'),
                           ('catalogue_row_number', 1)]:
            _, _, full, _, selection, cfg = fixture()
            selection['rows'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_download_requests(full, selection, cfg)

    def test_kind_issuer_parameter_field_route_or_method_cannot_drift(self):
        for before, after in [('step=9', 'step=1'), ('kind=F', 'kind=A'), ('co_id=6674', 'co_id=2324'),
                              ('SKEY1=', 'SKEY1=guessed'), ('YEAR=', 'YEAR=115')]:
            _, _, full, _, selection, cfg = fixture()
            cfg['requests'][0]['data'] = cfg['requests'][0]['data'].replace(before, after)
            with self.subTest(field=before), self.assertRaises(ValueError):
                validate_download_requests(full, selection, cfg)
        for key, value in [('url', 'https://foreign.example/book.pdf'), ('method', 'GET')]:
            _, _, full, _, selection, cfg = fixture()
            cfg['requests'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_download_requests(full, selection, cfg)

    def test_readfile2_own_assignments_and_complete_form_are_required(self):
        for failure in ('script', 'form', 'duplicate'):
            _, _, full, _, selection, cfg = fixture()
            if failure == 'script':
                full['scripts'][0]['text'] = full['scripts'][0]['text'].replace('step.value = 9', 'step.value = 8')
            elif failure == 'form':
                full['forms'][0]['controls'].pop()
            else:
                full['forms'].append(copy.deepcopy(full['forms'][0]))
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                validate_download_requests(full, selection, cfg)

    def test_charset_and_catalogue_body_binding_cannot_change(self):
        _, _, full, _, selection, cfg = fixture()
        selection['source_catalogue']['body_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'source bytes'):
            validate_download_requests(full, selection, cfg)


if __name__ == '__main__':
    unittest.main()

import hashlib
import unittest
from operating_windows_recovery import URL, validated_pdf, extract_tsmc_text


class WindowsRecoveryTest(unittest.TestCase):
    def metadata(self,body):
        return dict(exit_code=0,curl=dict(http_code=200,url_effective=URL),url=URL,
                    sha256=hashlib.sha256(body).hexdigest(),size_bytes=len(body))

    def test_original_hash_and_format(self):
        body=b'%PDF-1.7 test fixture'
        self.assertEqual(validated_pdf(body,self.metadata(body)),body)
        with self.assertRaisesRegex(ValueError,'hash/size'):
            validated_pdf(body+b'changed',self.metadata(body))

    def test_http_error_and_html_never_become_pdf(self):
        body=b'<html>Access denied</html>';meta=self.metadata(body)
        with self.assertRaisesRegex(ValueError,'PDF'):validated_pdf(body,meta)
        meta['curl']['http_code']=403
        with self.assertRaisesRegex(ValueError,'successful'):validated_pdf(body,meta)
        meta=self.metadata(b'%PDF-test');meta['exit_code']=22
        with self.assertRaisesRegex(ValueError,'successful'):validated_pdf(b'%PDF-test',meta)

    def test_unexpected_redirect_rejected(self):
        body=b'%PDF-test';meta=self.metadata(body);meta['curl']['url_effective']='https://example.com/mirror.pdf'
        with self.assertRaisesRegex(ValueError,'URL'):validated_pdf(body,meta)

    def test_financial_fields_and_wrong_period(self):
        text=('TSMC January 16, 2025 fourth quarter ended December 31, 2024 TIFRS consolidated '
              'consolidated revenue of NT$868.46 billion diluted earnings per share of NT$14.45 '
              'Gross margin for the quarter was 59.0%')
        values=extract_tsmc_text(text)
        self.assertEqual(values['gross_margin_pct'],59.0)
        self.assertEqual(values['revenue_twd_billions'],868.46)
        self.assertEqual(values['eps_twd'],14.45)
        with self.assertRaisesRegex(ValueError,'Issuer/period'):extract_tsmc_text(text.replace('December 31, 2024','December 31, 2025'))
        with self.assertRaisesRegex(ValueError,'conflicting'):extract_tsmc_text(text+' Gross margin for the quarter was 40.0%')


if __name__=='__main__':unittest.main()

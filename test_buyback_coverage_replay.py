import unittest
from buyback_coverage_replay import choose_response


class RecoveryChoiceTests(unittest.TestCase):
    def setUp(self):
        self.repair={'failed_filename':'old.html','replacement_filename':'new.html','url':'https://mopsov.twse.com.tw/original','failed_body_sha256':'failedhash'}
        self.old={'request':{'filename':'old.html','url':self.repair['url']},'http_status':502,'exit_code':0,'sha256':'failedhash'}
        self.new={'request':{'filename':'new.html','url':self.repair['url']},'http_status':200,'exit_code':0}

    def test_only_declared_failed_response_can_be_recovered(self):
        self.assertEqual(choose_response(self.old,{'old.html':b'502'},self.new,{'new.html':b'original'},self.repair),(b'original',True))
        self.assertEqual(self.old['http_status'],502)

    def test_successful_old_version_is_never_replaced_by_newer_response(self):
        old=dict(self.old,http_status=200)
        self.assertEqual(choose_response(old,{'old.html':b'old version'},self.new,{'new.html':b'new version'},self.repair),(b'old version',False))

    def test_other_failure_or_changed_failed_body_is_not_substituted(self):
        for change in [{'http_status':404},{'sha256':'different'}]:
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'Undeclared'):
                choose_response(dict(self.old,**change),{},self.new,{'new.html':b'original'},self.repair)

    def test_recovery_wrong_url_or_transport_fails(self):
        for new in [dict(self.new,http_status=502),dict(self.new,exit_code=28),dict(self.new,request={'filename':'new.html','url':'https://other/original'})]:
            with self.subTest(new=new),self.assertRaisesRegex(ValueError,'Recovery transport/request'):
                choose_response(self.old,{},new,{'new.html':b'original'},self.repair)


if __name__=='__main__':unittest.main()

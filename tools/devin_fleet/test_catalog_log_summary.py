import json
import os
from pathlib import Path
import tempfile
import unittest
import catalog_log_summary as logs


class LogTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir='/tmp');self.addCleanup(t.cleanup);self.root=Path(t.name)
    def file(self,name='devin_2026-09-20T06-02-04_123.log',raw=b'ERROR TLS certificate failure; Authorization: SECRET\nretry timeout'):
        p=self.root/name;p.write_bytes(raw);p.chmod(0o600);os.utime(p,(logs.START+30,logs.START+30));return p
    def test_finite_summary_never_exports_secret_text_or_names(self):
        p=self.file();v=logs.collect(str(self.root))
        self.assertEqual(v['candidate_count'],1);self.assertEqual(v['categories']['tls_failure'],1)
        self.assertFalse(v['attempt_bound']);self.assertFalse(v['cli_executed'])
        for forbidden in ('SECRET','Authorization',p.name):self.assertNotIn(forbidden,json.dumps(v))
    def test_old_and_unrelated_files_not_read(self):
        p=self.file();os.utime(p,(logs.START-1,logs.START-1));self.file('credentials.json')
        self.assertEqual(logs.collect(str(self.root))['candidate_count'],0)
    def test_symlink_and_hardlink_refused(self):
        p=self.file();target=self.root/'target';p.rename(target);p.symlink_to(target)
        os.utime(p,(logs.START+30,logs.START+30),follow_symlinks=False)
        with self.assertRaises(OSError):logs.collect(str(self.root))
        p.unlink();os.link(target,p)
        with self.assertRaises(ValueError):logs.collect(str(self.root))
    def test_world_write_refused(self):
        p=self.file();p.chmod(0o666)
        with self.assertRaises(ValueError):logs.collect(str(self.root))
    def test_category_counts_capped(self):
        self.assertEqual(logs.classify(b'error '*2000)['error_level'],1000)

    def test_context_is_same_line_and_does_not_export_url(self):
        v=logs.classify(b'updater status 403 https://static.devin.ai/private?token=SECRET\nserver.codeium.com models success')
        self.assertEqual(v['rejection_line_static_host'],1)
        self.assertEqual(v['rejection_line_update'],1)
        self.assertEqual(v['rejection_line_backend_host'],0)
        self.assertEqual(v['rejection_line_model_catalog'],0)
        self.assertNotIn('SECRET',json.dumps(v))
        self.assertEqual(logs.classify(b'403 server.codeium.com.evil')['rejection_line_backend_host'],0)

    def test_auth_types_are_distinct_without_exporting_payload(self):
        for word,key in ((b'unauthorized','auth_unauthorized'),(b'unauthenticated','auth_unauthenticated'),
                         (b'forbidden','auth_forbidden'),(b'token rejected','auth_token_rejected')):
            result=logs.classify(b'ERROR '+word+b' Authorization: SECRET')
            self.assertEqual(result[key],1)
            self.assertEqual(result['auth_rejection'],1)
            self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(logs.classify(b'status: 403')['http_403'],1)
        self.assertEqual(logs.classify(b'status: 401')['http_401'],1)


if __name__=='__main__':unittest.main()

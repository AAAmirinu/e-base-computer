import json
import unittest
from unittest.mock import patch
import catalog_endpoint_probe as probe
from model_network_admission import MODEL_HOSTS, FEATURE_HOST


class EndpointTests(unittest.TestCase):
    def test_exact_hosts_and_four_bounded_calls(self):
        self.assertEqual({host+':443' for host in probe.HOSTS},MODEL_HOSTS|{FEATURE_HOST})
        def capture(argv,cwd,**kwargs):
            self.assertEqual(argv[:4],['/usr/bin/python3','-I','-c',probe.PROBE])
            self.assertEqual(cwd,'/')
            self.assertEqual(kwargs,{'timeout':6})
            return json.dumps(dict(host=argv[4],status=302,error_class=None)).encode(),0
        with patch.object(probe,'_capture',side_effect=capture) as mocked:
            result=probe.probe_endpoints()
        self.assertEqual(mocked.call_count,4)
        self.assertEqual([row['host'] for row in result],list(probe.HOSTS))
        self.assertTrue(all(row['status']==302 for row in result))

    def test_timeout_is_finite_and_not_retried(self):
        error=probe.CaptureDeadline(leader_exited=False,stdout_bytes=0,stderr_bytes=0,open_streams=['out'])
        with patch.object(probe,'_capture',side_effect=error) as mocked:
            result=probe.probe_endpoints()
        self.assertEqual(mocked.call_count,4)
        self.assertTrue(all(row['error_class']=='capture_deadline' for row in result))

    def test_invalid_receipts_fail_closed(self):
        host=probe.HOSTS[0]
        rows=[dict(host=host,status=True,error_class=None),dict(host=host,status=600,error_class=None),
              dict(host=host,status=None,error_class='secret error'),
              dict(host='example.com',status=200,error_class=None),
              dict(host=host,status=200,error_class='tls'),
              dict(host=host,status=200,error_class=None,headers={})]
        for row in rows:
            with self.subTest(row=row),patch.object(probe,'_capture',return_value=(json.dumps(row).encode(),0)):
                with self.assertRaises(ValueError):probe.probe_endpoints()
        with self.assertRaises(ValueError):probe.validate({},['api.devin.ai'])

    def test_bad_capture_and_duplicate_keys(self):
        for raw,code in [(b'{}',False),(b'{}',1),(b'x'*513,0),
                         (b'{"host":"api.devin.ai","host":"api.devin.ai","status":200,"error_class":null}',0)]:
            with self.subTest(code=code),patch.object(probe,'_capture',return_value=(raw,code)):
                with self.assertRaises(ValueError):probe.probe_endpoints()

    def test_child_contract_has_no_body_or_redirect_operation(self):
        compile(probe.PROBE,'<endpoint-probe>','exec')
        self.assertIn('os.environ.clear()',probe.PROBE)
        self.assertIn("connection.request('HEAD','/'",probe.PROBE)
        self.assertNotIn('response.read(',probe.PROBE)
        self.assertNotIn('getheader(',probe.PROBE)


if __name__=='__main__':unittest.main()

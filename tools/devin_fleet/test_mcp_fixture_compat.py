import io
import json
from pathlib import Path
import types
import unittest
import mcp_denial_fixture as original
from mcp_fixture_compat import compatible_source,adapt_inputs,OLD,NEW
import hashlib
import mcp_echo_control_inputs

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.raw=Path(original.__file__).read_bytes()
        self.fixed=types.ModuleType('trusted_compatible_fixture')
        exec(compile(compatible_source(self.raw),'<trusted-compatible-fixture>','exec'),self.fixed.__dict__)

    def messages(self,identity):
        return [dict(jsonrpc='2.0',id=1,method='initialize',params={}),
                dict(jsonrpc='2.0',id=2,method='tools/list'),
                dict(jsonrpc='2.0',id=identity,method='tools/call',params={'name':'echo','arguments':{}}),
                dict(jsonrpc='2.0',id=3,method='ping')]

    def run_server(self,module,messages,events,sink):
        module.serve(io.StringIO(''.join(json.dumps(v)+'\n' for v in messages)),sink,events.append)

    def test_reproduces_original_call_then_connection_exit(self):
        events=[];sink=io.StringIO()
        with self.assertRaisesRegex(ValueError,'numeric request id'):
            self.run_server(original,self.messages('call-one'),events,sink)
        self.assertEqual(events,['initialized','listed','called'])
        self.assertEqual(len(sink.getvalue().splitlines()),2)
        self.assertNotIn(original.MARKER,sink.getvalue())

    def test_fixed_string_ids_reply_and_keep_stream_alive(self):
        for identity in ('call-one','', '日本語', 'x'*128,0,-1,2**53-1,-(2**53-1)):
            with self.subTest(identity=identity):
                events=[];sink=io.StringIO()
                self.run_server(self.fixed,self.messages(identity),events,sink)
                rows=[json.loads(v) for v in sink.getvalue().splitlines()]
                self.assertEqual(len(rows),4)
                self.assertEqual(rows[2]['id'],identity)
                self.assertEqual(rows[2]['result']['content'][0]['text'],original.MARKER)
                self.assertEqual(rows[3]['result'],{})
                self.assertEqual(events,['initialized','listed','called'])

    def test_invalid_ids_still_rejected(self):
        for identity in (None,True,1.0,2**53,-2**53,'x'*129,'日'*43,[],{}):
            with self.subTest(identity=identity),self.assertRaises(ValueError):
                self.fixed.reply(self.messages(identity)[2])

    def test_payload_and_extra_metadata_still_refused(self):
        for params in ({'name':'other','arguments':{}},{'name':'echo','arguments':{'secret':'value'}},
                       {'name':'echo','arguments':{},'_meta':{}}):
            request=self.messages('one')[2];request['params']=params
            value=self.fixed.reply(request)
            self.assertEqual(value['error']['code'],-32602)
            self.assertNotIn('secret',json.dumps(value))

    def test_only_id_guard_changes_no_historical_mutation(self):
        self.assertEqual(compatible_source(self.raw).decode(),self.raw.decode().replace(OLD,NEW,1))
        self.assertEqual(Path(original.__file__).read_bytes(),self.raw)
        for raw in (b'',b'x'*16385,compatible_source(self.raw),self.raw+self.raw):
            with self.assertRaises(ValueError):compatible_source(raw)

    def test_builder_changes_only_fixture_and_bound_runner(self):
        inputs=mcp_echo_control_inputs.build_inputs('/tmp/e-base-mcp-probe-abcdefgh','a'*32,(1,2))
        before=dict(inputs);updated=adapt_inputs(inputs)
        self.assertEqual(inputs,before)
        self.assertEqual({k for k in inputs if inputs[k]!=updated[k]},{'fixture.py','runner.py'})
        self.assertIn(hashlib.sha256(updated['fixture.py']).hexdigest().encode(),updated['runner.py'])
        self.assertNotIn(hashlib.sha256(inputs['fixture.py']).hexdigest().encode(),updated['runner.py'])
        self.assertEqual(updated['config.json'],inputs['config.json'])

    def test_runner_digest_drift_refused(self):
        inputs={'fixture.py':self.raw,'runner.py':b'pass\n'}
        with self.assertRaises(ValueError):adapt_inputs(inputs)
        digest=hashlib.sha256(self.raw).hexdigest().encode()
        inputs['runner.py']=b'# '+digest+b' '+digest
        with self.assertRaises(ValueError):adapt_inputs(inputs)

if __name__=='__main__':unittest.main()

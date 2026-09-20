import io
import json
import types
import unittest
import mcp_echo_control_inputs as inputs
from mcp_fixture_compat import adapt_inputs as id_inputs
from mcp_fixture_params import adapt_inputs

class ParamsTests(unittest.TestCase):
    def setUp(self):
        self.original=inputs.build_inputs('/tmp/e-base-mcp-probe-abcdefgh','a'*32,(1,2))
        self.idonly=self.module(id_inputs(self.original)['fixture.py'])
        self.fixed_inputs=adapt_inputs(self.original)
        self.fixed=self.module(self.fixed_inputs['fixture.py'])
    def module(self,source):
        value=types.ModuleType('trusted_fixture_test')
        exec(compile(source,'<trusted-fixture-test>','exec'),value.__dict__)
        return value
    def request(self,params):return dict(jsonrpc='2.0',id='call-one',method='tools/call',params=params)

    def test_reproduces_valid_params_rejection_and_fixed_success(self):
        for params in ({'name':'echo'},{'name':'echo','arguments':{},'_meta':{'progressToken':123}},
                       {'name':'echo','_meta':{'progressToken':'SECRET'}}):
            request=self.request(params)
            self.assertEqual(self.idonly.reply(request)['error']['code'],-32602)
            result=self.fixed.reply(request)
            self.assertEqual(result['result']['content'][0]['text'],self.fixed.MARKER)
            self.assertNotIn('SECRET',json.dumps(result))

    def test_other_execution_and_invalid_metadata_rejected(self):
        for params in ({'name':'other'},{'name':'echo','arguments':{'x':1}},
                       {'name':'echo','arguments':None},{'name':'echo','arguments':'{}'},
                       {'name':'echo','task':{}},{'name':'echo','_meta':None},
                       {'name':'echo','_meta':{'x':float('nan')}},
                       {'name':'echo','_meta':{'x':'a'*1024}}):
            self.assertEqual(self.fixed.reply(self.request(params))['error']['code'],-32602)

    def test_server_stream_continues_and_audits_once(self):
        messages=[self.request({'name':'echo','_meta':{'progressToken':1}}),dict(jsonrpc='2.0',id=2,method='ping')]
        sink=io.StringIO();events=[]
        self.fixed.serve(io.StringIO(''.join(json.dumps(x)+'\n' for x in messages)),sink,events.append)
        self.assertEqual(len(sink.getvalue().splitlines()),2)
        self.assertEqual(events,['called'])

    def test_old_inputs_preserved(self):
        self.assertEqual(self.original,inputs.build_inputs('/tmp/e-base-mcp-probe-abcdefgh','a'*32,(1,2)))
        self.assertEqual({k for k in self.original if self.original[k]!=self.fixed_inputs[k]},{'fixture.py','runner.py'})

if __name__=='__main__':unittest.main()

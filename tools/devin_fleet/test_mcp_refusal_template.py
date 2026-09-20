import json
import unittest
from test_mcp_wildcard_denial_evidence import sequence, audit, NONCE
from mcp_refusal_template import summarize, validate, APPROVAL_REQUIRED


class TemplateTests(unittest.TestCase):
    def test_server_approval_requires_exact_complete_fixed_message(self):
        data=sequence()
        for text,expected in ((APPROVAL_REQUIRED,True),(APPROVAL_REQUIRED+' ',False),
                ('Example: '+APPROVAL_REQUIRED,False),(APPROVAL_REQUIRED.replace('echo','other'),False)):
            data['steps'][3]['observation']['results'][0]['content']=text
            self.assertEqual(summarize(data,audit(),NONCE)['server_approval_required_exact'],expected)

    def test_fixed_fixture_names_and_ordinary_permissions_only(self):
        data=sequence()
        data['steps'][3]['observation']['results'][0]['content']="Permission to call MCP tool 'echo' on server 'fleet-probe' was denied. The user chose to deny access for this MCP server."
        value=summarize(data,audit(),NONCE)
        self.assertNotIn('_',value['tokens'])
        self.assertFalse(value['truncated'])
        self.assertIn('fleet',value['tokens'])

    def test_projection_removes_free_text(self):
        data=sequence()
        data['steps'][3]['observation']['results'][0]['content']='Error: permission denied SECRET_TOKEN https://private.example/abc123'
        value=summarize(data,audit(),NONCE)
        self.assertTrue(value['linked_result'])
        self.assertEqual(value['tokens'][:4],['error',':','permission','denied'])
        self.assertNotIn('secret',json.dumps(value));self.assertNotIn('private',json.dumps(value))

    def test_unlinked_result_not_projected(self):
        data=sequence();data['steps'][3]['observation']['results'][0]['source_call_id']='other'
        self.assertEqual(summarize(data,audit(),NONCE),dict(linked_result=False,tokens=[],truncated=False,server_approval_required_exact=False))

    def test_limit_and_wire_rejection(self):
        data=sequence();data['steps'][3]['observation']['results'][0]['content']='denied '*200
        value=summarize(data,audit(),NONCE)
        self.assertEqual(len(value['tokens']),80);self.assertTrue(value['truncated'])
        with self.assertRaises(ValueError):validate(dict(linked_result=True,tokens=['SECRET'],truncated=False,server_approval_required_exact=False))


if __name__=='__main__':unittest.main()

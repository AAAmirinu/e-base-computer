import unittest
from mcp_override_probe import overrides, shape, validate, display_tokens, exact_get_display


class OverrideTests(unittest.TestCase):
    def test_exact_get_requires_identity_status_and_command(self):
        raw='Server: private\nStatus: disabled — disabled by user\nCommand: /usr/bin/false\n'.encode()
        self.assertTrue(exact_get_display(raw,'private',True))
        for changed in (raw+b'extra\n', raw.replace(b'/false',b'/false-extra'),
                        raw.replace(b'Server: private',b'Server: other'),raw.replace(b'disabled',b'enabled'),b'\x1b[0m'+raw):
            self.assertFalse(exact_get_display(changed,'private',True))

    def test_fixed_vocabulary_redacts_names_and_values(self):
        result=display_tokens(b'PRIVATE_NAME (disabled)\nCommand: /usr/bin/false\nURL: https://SECRET/TOKEN',('PRIVATE_NAME',))
        self.assertEqual(result[0],['inherited_name','open_paren','word_disabled','close_paren'])
        self.assertEqual(result[1],['word_command','colon','false_command'])
        self.assertNotIn('PRIVATE',repr(result))
        self.assertNotIn('SECRET',repr(result))
        self.assertNotIn('TOKEN',repr(result))

    def test_override_copies_names_not_values(self):
        value=overrides(b'{"mcpServers":{"existing":{"url":"SECRET","env":{"TOKEN":"SECRET"}}}}')
        self.assertEqual(value['existing'],{'command':'/usr/bin/false','disabled':True})
        self.assertFalse(value['fleet-probe']['disabled'])
        self.assertNotIn('SECRET',repr(value))

    def test_conflict_and_invalid_names_refused(self):
        for raw in (b'{"mcpServers":{"fleet-probe":{}}}',b'{"mcpServers":{"../evil":{}}}',b'{"mcpServers":{}}'):
            with self.assertRaises(ValueError): overrides(raw)

    def test_output_shape_never_reflects_values(self):
        result=shape(b'{"url":"SECRET","disabled":true}',0)
        self.assertTrue(result['root_disabled_true'])
        self.assertNotIn('SECRET',repr(result))
        unknown=shape(b'SECRET\n',1)
        self.assertFalse(unknown['json_object'])
        self.assertEqual(unknown['line_count'],1)

    def test_observation_cannot_claim_acceptance(self):
        value=dict(model_executed=False,override_verified=False,raw_values_exported=False,
                   global_config_unchanged=True,commands=[],status='observed')
        validate(value)
        value['override_verified']=True
        with self.assertRaises(ValueError): validate(value)


if __name__=='__main__': unittest.main()

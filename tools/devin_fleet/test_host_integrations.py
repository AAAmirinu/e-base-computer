import unittest
from inspect_host_integrations import setting_observation, mcp_shape, inspect_shape, registration_metadata


class IntegrationTests(unittest.TestCase):
    def test_registration_metadata_no_private_value_or_reference(self):
        result = registration_metadata({'image':'private.registry/image:tag',
                                        'agent':'devin', 'credentials':'secret-value'})
        self.assertIsNone(result['public_template_reference'])
        self.assertTrue(result['agent_is_devin'])
        self.assertNotIn('secret-value', str(result))
        self.assertFalse(result['credential_configuration_verified'])

    def test_public_image_namespace_exact(self):
        good = 'docker.io/docker/sandbox-templates:devin'
        self.assertEqual(registration_metadata({'image':good})['public_template_reference'], good)
        for bad in (good+'/secret', 'attacker/docker/sandbox-templates:devin', None, []):
            self.assertIsNone(registration_metadata({'image':bad})['public_template_reference'])

    def test_inspect_shape_suppresses_values_and_unknown_names(self):
        result = inspect_shape({'credentials': {'private-name': 'secret'},
                                'name': 'private-name', 'kits': ['secret']})
        self.assertNotIn('private-name', str(result))
        self.assertNotIn('secret', str(result))
        self.assertEqual(result['fields']['credentials']['other_field_count'], 1)

    def test_inspect_shape_depth_and_samples_bounded(self):
        self.assertEqual(len(inspect_shape([{}]*20)['samples']), 4)
        value = {'config': {'config': {'config': {'config': {'config': 'secret'}}}}}
        self.assertIn('depth_limit', str(inspect_shape(value)))
        self.assertNotIn('secret', str(inspect_shape(value)))
    def test_exact_boolean(self):
        self.assertEqual(setting_observation('false\n'), dict(recognized=True, enabled=False))
        self.assertEqual(setting_observation('true'), dict(recognized=True, enabled=True))
        for value in ('0', 'FALSE', 'key: false', 'private-token'):
            self.assertEqual(setting_observation(value), dict(recognized=False))

    def test_no_server_values_exported(self):
        result = mcp_shape('[{"name":"private","headers":{"token":"secret"}}]')
        self.assertEqual(result['entries'], 1)
        self.assertNotIn('secret', str(result))
        self.assertFalse(result['empty_inventory_verified'])

    def test_empty_list(self):
        self.assertTrue(mcp_shape('[]')['empty_inventory_verified'])

    def test_gateway_metadata_values_suppressed(self):
        result = mcp_shape('{"servers":[],"gateway":{"url":"private","auth":"secret"}}')
        self.assertEqual(result['metadata_fields_present'], ['gateway'])
        self.assertEqual(result['unknown_fields'], 0)
        self.assertEqual(result['fields']['servers']['count'], 0)
        self.assertNotIn('private', str(result))
        self.assertNotIn('secret', str(result))
        self.assertFalse(result['empty_inventory_verified'])

    def test_unknown_object_not_empty_proof(self):
        for raw in ('{}', '{"servers":[]}', '{"secret": "value"}'):
            result = mcp_shape(raw)
            self.assertFalse(result['empty_inventory_verified'])
            self.assertNotIn('secret', str(result))

    def test_malformed_or_duplicate(self):
        for raw in ('null', 'false', '{"servers":[],"servers":[1]}', 'bad'):
            with self.assertRaises(ValueError):
                mcp_shape(raw)


if __name__ == '__main__':
    unittest.main()

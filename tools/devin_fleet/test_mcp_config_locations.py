import unittest
from unittest.mock import patch
from mcp_config_locations import collect, validate, PATHS


class LocationsTests(unittest.TestCase):
    def test_only_metadata_and_environment_booleans(self):
        with patch('mcp_config_locations.Path.lstat', side_effect=FileNotFoundError), \
                patch.dict('os.environ', {'HOME':'/home/agent', 'XDG_CONFIG_HOME':'SECRET'}, clear=True):
            result=validate(collect())
        self.assertEqual(set(result['paths']),set(PATHS))
        self.assertTrue(result['environment_present']['XDG_CONFIG_HOME'])
        self.assertNotIn('SECRET',repr(result))
        self.assertFalse(result['configuration_isolated'])

    def test_errors_are_not_absence(self):
        with patch('mcp_config_locations.Path.lstat', side_effect=PermissionError):
            value=validate(collect())
        self.assertEqual(set(value['paths'].values()),{'inaccessible'})
        value['configuration_isolated']=True
        with self.assertRaises(ValueError): validate(value)


if __name__=='__main__': unittest.main()

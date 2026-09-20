import unittest
from unittest.mock import patch, mock_open
import mcp_cli_policy_static as static


class StaticTests(unittest.TestCase):
    def test_only_fixed_binary_and_markers(self):
        raw=b'x'*100+b'Permission to call tool'+b'x'*100
        with patch.object(static,'verify_cli') as verify, patch.object(static.os.path,'realpath',return_value='/fixed'), patch('builtins.open',mock_open(read_data=raw)), patch.object(static,'PIN',static.hashlib.sha256(raw).hexdigest()):
            value=static.inspect()
        verify.assert_called_once()
        self.assertEqual(len(value['contexts']),1)
        self.assertFalse(value['cli_executed'])

    def test_wrong_binary_fails(self):
        with patch.object(static,'verify_cli'), patch.object(static.os.path,'realpath',return_value='/fixed'), patch('builtins.open',mock_open(read_data=b'wrong')):
            with self.assertRaises(ValueError):static.inspect()

    def test_unknown_marker_and_excess_text_rejected(self):
        for item in (dict(marker='other',context='x'),dict(marker=static.MARKERS[0],context='x'*1751)):
            with self.assertRaises(ValueError):static.validate(dict(binary_sha256=static.PIN,contexts=[item],cli_executed=False,model_executed=False))


if __name__=='__main__':unittest.main()

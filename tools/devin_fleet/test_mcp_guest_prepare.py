import base64
import json
from pathlib import Path
import unittest
import zlib
from unittest.mock import patch
import guest_mcp_prepare as preparation
from guest_mcp_prepare import encode_sources, decode_sources, MODULES, validate


class GuestPrepareTests(unittest.TestCase):
    def test_discovery_refuses_old_state_before_any_decode_or_write(self):
        with patch.object(preparation,'decode_sources') as decode:
            for state,source in ((preparation.DISCOVERY_STATE,None),(preparation.STATE,'pass'),(preparation.DISCOVERY_STATE,''),
                                 (preparation.DISCOVERY_STATE,'x'*16385)):
                with self.assertRaises(ValueError):
                    preparation.prepare('invalid',state_directory=state,discovery_source=source)
            decode.assert_not_called()

    def test_discovery_bootstrap_is_preparation_only(self):
        compile(preparation.DISCOVERY_PROBE,'<discovery>','exec')
        self.assertIn('state_directory=module.DISCOVERY_STATE',preparation.DISCOVERY_PROBE)
        self.assertNotIn('launch_reserved',preparation.DISCOVERY_PROBE)
        self.assertNotEqual(preparation.STATE,preparation.DISCOVERY_STATE)

    def test_trusted_bundle_roundtrip(self):
        sources=decode_sources(encode_sources(Path(__file__).parent))
        self.assertEqual(set(sources),set(MODULES))
        self.assertIn('def prepare_attempt',sources['mcp_probe_reservation.py'])

    def test_extra_path_and_bad_digest_rejected(self):
        payload=json.loads(zlib.decompress(base64.b64decode(encode_sources(Path(__file__).parent))))
        payload[MODULES[0]]['sha256']='0'*64
        with self.assertRaises(ValueError): decode_sources(base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode())
        payload['../bad.py']=payload[MODULES[0]]
        with self.assertRaises(ValueError): decode_sources(base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode())

    def test_prepare_is_not_admission(self):
        value=dict(prepared=True,model_executed=False,production_admitted=False,previous_session_inventory_verified=False,input_count=9)
        validate(value)
        value['production_admitted']=True
        with self.assertRaises(ValueError): validate(value)


if __name__=='__main__': unittest.main()

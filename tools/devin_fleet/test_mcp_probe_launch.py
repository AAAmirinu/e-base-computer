from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import mcp_probe_launch as launch
from mcp_probe_supervision import MACHINE, MARKER
from mcp_probe_inputs import make_input_builder, PROMPT
from mcp_probe_reservation import prepare_attempt, CLAIM


class LaunchTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(launch,'verify_cli'); p.start(); self.addCleanup(p.stop)
        temporary = tempfile.TemporaryDirectory(prefix='mcp-launch-test-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.inherited=b'{"mcpServers":{"synthetic":{"url":"https://synthetic.invalid"}}}'
        reader=patch.object(launch,'read_global',return_value=self.inherited)
        self.reader=reader.start()
        self.main=b'{}'
        self.reader.side_effect=lambda name: self.main if name=='config.json' else self.reader.return_value
        self.addCleanup(reader.stop)
        self.work, self.reservation = prepare_attempt(self.state, make_input_builder(self.inherited), previous_sessions=[])
        self.addCleanup(shutil.rmtree, self.work)
        self.catalog = json.dumps({'families': [{'variants': [
            {'model_uid': 'swe-2-high', 'cost_tier': 'Free'}]}]}).encode()
        date = patch.object(launch, 'datetime')
        self.clock = date.start()
        self.addCleanup(date.stop)
        self.clock.now.return_value = datetime(2026, 9, 20, tzinfo=timezone.utc)
        process = patch.object(launch, 'run_private_process', return_value={
            'returncode': 0, 'timed_out': False, 'leader_reaped': True,
            'process_group_stop_requested': True, 'all_descendants_stopped': False,
            'raw_output_suppressed': True})
        self.process = process.start()
        self.addCleanup(process.stop)

    def run_probe(self):
        return launch.launch_reserved(self.state, catalog_check=lambda: (self.catalog, 0))

    def supervised(self,**binding):
        self.assertGreater(binding.pop('timeout'),0)
        now=int(time.time())
        return json.dumps(dict(binding,schema=2,machine_vm_id=MACHINE,lease_id='b'*32,
            issued_at=now,expires_at=now+120,session_inventory_scope='current_workdir',
            session_inventory_verified=True,fresh_attempt_preconditions_verified=True,
            previous_sessions=['old-session'])).encode()

    def prepare_hold(self):
        (self.state/'prepare-only').touch(mode=0o600)
        path=self.state/'prepared.json'
        path.write_text(json.dumps(dict(prepared=True,model_executed=False,production_admitted=False,
                                       previous_session_inventory_verified=False,input_count=9)))
        path.chmod(0o600)

    def test_supervised_single_launch_keeps_hold(self):
        self.prepare_hold()
        result=launch.launch_reserved(self.state,supervised_check=self.supervised,catalog_check=lambda:(self.catalog,0))
        self.assertFalse(result['passed'])
        self.assertTrue((self.state/'prepare-only').exists())
        self.assertTrue((self.state/CLAIM/MARKER).exists())
        saved=json.loads((self.state/CLAIM/'launch.json').read_bytes())
        self.assertEqual(saved['supervision']['receipt']['previous_sessions'],['old-session'])
        with self.assertRaises(FileExistsError):
            launch.launch_reserved(self.state,supervised_check=self.supervised)
        self.assertEqual(self.process.call_count,1)

    def test_catalog_failure_consumes_supervised_attempt(self):
        self.prepare_hold()
        with patch.object(launch,'read_catalog',side_effect=TimeoutError) as catalog:
            with self.assertRaises(TimeoutError): launch.launch_reserved(self.state,supervised_check=self.supervised)
            with self.assertRaises(FileExistsError): launch.launch_reserved(self.state,supervised_check=self.supervised)
            self.assertEqual(catalog.call_count,1)
        self.assertTrue((self.state/'prepare-only').exists())
        self.process.assert_not_called()

    def test_expired_supervision_blocks_catalog(self):
        self.prepare_hold()
        def expired(**binding):
            receipt=json.loads(self.supervised(**binding))
            receipt['issued_at']-=240; receipt['expires_at']-=240
            return json.dumps(receipt).encode()
        with patch.object(launch,'read_catalog') as catalog:
            with self.assertRaises(ValueError): launch.launch_reserved(self.state,supervised_check=expired)
            catalog.assert_not_called()
        self.process.assert_not_called()

    def test_export_created_by_callback_blocks_admission_and_catalog(self):
        self.prepare_hold()
        def changed(**binding):
            (self.work/'export.json').touch(mode=0o600)
            return self.supervised(**binding)
        with patch.object(launch,'read_catalog') as catalog:
            with self.assertRaises(ValueError): launch.launch_reserved(self.state,supervised_check=changed)
            catalog.assert_not_called()
        self.process.assert_not_called()
        self.assertFalse((self.state/CLAIM/MARKER).exists())

    def test_supervision_requires_existing_hold(self):
        with self.assertRaises(ValueError): launch.launch_reserved(self.state,supervised_check=self.supervised)
        self.process.assert_not_called()

    def test_catalog_timeout_respects_short_admission(self):
        self.prepare_hold()
        def short(**binding):
            value=json.loads(self.supervised(**binding))
            value['expires_at']=value['issued_at']+2
            return json.dumps(value).encode()
        with patch.object(launch,'read_catalog',return_value=(self.catalog,0)) as catalog:
            launch.launch_reserved(self.state,supervised_check=short)
        self.assertGreater(catalog.call_args.kwargs['timeout'],0)
        self.assertLessEqual(catalog.call_args.kwargs['timeout'],2)

    def test_fixed_single_launch_and_reentry_refusal(self):
        result = self.run_probe()
        self.assertFalse(result['passed'])
        self.assertFalse(result['all_descendants_stopped'])
        self.assertEqual(result['phase'], 'awaiting_vm_stop')
        argv = self.process.call_args.args[0]
        self.assertEqual(argv[0], '/home/agent/.local/bin/devin-cli')
        self.assertNotIn('--resume', argv)
        self.assertEqual(argv[-1], PROMPT)
        self.assertEqual(argv[argv.index('--permission-mode')+1], 'normal')
        with self.assertRaises(FileExistsError): self.run_probe()
        self.assertEqual(self.process.call_count, 1)

    def test_spawn_failure_keeps_attempt(self):
        self.process.side_effect = OSError('synthetic spawn failure')
        with self.assertRaises(OSError): self.run_probe()
        self.assertTrue((self.state/CLAIM/'launch.json').exists())
        with self.assertRaises(FileExistsError): self.run_probe()
        self.assertEqual(self.process.call_count, 1)

    def test_paid_model_blocks_spawn(self):
        self.catalog = self.catalog.replace(b'Free', b'Paid')
        with self.assertRaises(ValueError): self.run_probe()
        self.process.assert_not_called()

    def test_expiry_blocks_spawn(self):
        self.clock.now.return_value = datetime(2026, 10, 10, tzinfo=timezone.utc)
        with self.assertRaises(ValueError): self.run_probe()
        self.process.assert_not_called()

    def test_changed_input_during_catalog_consumes_but_does_not_launch(self):
        def catalog():
            (self.work/'prompt.txt').write_bytes(b'changed')
            return self.catalog, 0
        with self.assertRaises(ValueError): launch.launch_reserved(self.state, catalog_check=catalog)
        self.assertTrue((self.state/CLAIM/'launch.json').exists())
        self.process.assert_not_called()

    def test_timeout_never_becomes_pass(self):
        self.process.return_value.update(returncode=-9, timed_out=True)
        result = self.run_probe()
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['passed'])

    def test_inherited_change_during_catalog_holds_attempt(self):
        def catalog():
            self.reader.return_value=b'{"mcpServers":{}}'
            return self.catalog,0
        with self.assertRaises(ValueError): launch.launch_reserved(self.state,catalog_check=catalog)
        self.process.assert_not_called()
        self.assertTrue((self.state/CLAIM/'launch.json').exists())

    def test_unbound_config_refused_before_read(self):
        with self.assertRaises(ValueError):
            launch.check_inherited({'inherited-mcp.sha256':b'unbound\n'})
        self.reader.assert_not_called()
        self.process.assert_not_called()

    def test_default_uses_fresh_bounded_catalog_reader(self):
        with patch.object(launch,'read_catalog',return_value=(self.catalog,0)) as reader:
            result=launch.launch_reserved(self.state)
        reader.assert_called_once_with(str(self.work),timeout=60)
        self.assertFalse(result['passed'])

    def test_elapsed_catalog_cannot_extend_admission(self):
        self.prepare_hold()
        current=[1000]
        def catalog():
            current[0]+=121
            return self.catalog,0
        with patch.object(launch.time,'time',side_effect=lambda:current[0]):
            with self.assertRaises(ValueError):
                launch.launch_reserved(self.state,supervised_check=self.supervised,catalog_check=catalog)
        self.process.assert_not_called()
        self.assertTrue((self.state/CLAIM/MARKER).exists())
        self.assertTrue((self.state/CLAIM/'launch.json').exists())

    def test_prepare_only_hold_prevents_catalog_and_model(self):
        (self.state/'prepare-only').touch(mode=0o600)
        with patch.object(launch,'read_catalog') as reader:
            with self.assertRaises(ValueError): launch.launch_reserved(self.state)
        reader.assert_not_called()
        self.process.assert_not_called()

    def test_hooks_and_migration_block_even_catalog(self):
        for raw in (b'{"hooks":{"startup":"forbidden"}}',b'{"mcpServers":{"old":{}}}',
                    b'{"hooks":null}',b'[]',b'{"hooks":{},"hooks":{}}'):
            with self.subTest(raw=raw),patch.object(launch,'read_catalog') as catalog:
                self.main=raw
                with self.assertRaises(ValueError): launch.launch_reserved(self.state)
                catalog.assert_not_called()
                self.process.assert_not_called()
                self.assertFalse((self.state/CLAIM/'launch.json').exists())

    def test_main_change_during_catalog_preserves_attempt_without_spawn(self):
        def catalog():
            self.main=b'{"notify":"never"}'
            return self.catalog,0
        with self.assertRaises(ValueError): launch.launch_reserved(self.state,catalog_check=catalog)
        self.process.assert_not_called()
        self.assertTrue((self.state/CLAIM/'launch.json').exists())


if __name__ == '__main__': unittest.main()

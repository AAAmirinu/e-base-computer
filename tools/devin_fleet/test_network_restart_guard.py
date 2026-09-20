"""Restart gate uses private synthetic journals; no VM or real policy calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import network_restart_guard as guard
from network_recovery_record import expected_record
from sandbox_turn_fence import reserve_turn


class RestartGuardTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.run=self.root/'turn'
        self.run.mkdir(mode=0o700)
        self.epoch='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.vm='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        self.reg={'controller_root':str(self.root),'migration_epoch':self.epoch,
                  'roles':{'machine':{'id':self.vm}}}
        reserve_turn(self.root,dict(schema=1,operation_id='c'*32,role='machine',sequence=0,
                     migration_epoch=self.epoch,sandbox_id=self.vm),self.run)
        self.window=self.run/'network-window'
        self.record=dict(schema=1,role='machine',sandbox_id=self.vm,phase='closed',
                         network_denied_after=True,automatic_resume=False,created_deny_ids=[])

    def write(self,value=None):
        self.window.mkdir(mode=0o700,exist_ok=True)
        path=self.window/'network-window.json'
        path.write_text(json.dumps(self.record if value is None else value))
        path.chmod(0o600)

    def inspect(self):
        return guard.inspect_windows(self.root,self.reg)

    def recovery(self):
        fence_raw=(self.root/'model-turn-fences'/'machine.json').read_bytes()
        window_raw=(self.window/'network-window.json').read_bytes()
        record=expected_record(fence_raw,window_raw,self.reg,'machine')
        directory=self.window/'recovery'
        directory.mkdir(mode=0o700)
        path=directory/'recovery.json'
        path.write_text(json.dumps(record))
        path.chmod(0o600)
        return path,record

    def test_partial_original_can_be_bound_by_separate_recovery_not_rewritten(self):
        self.write()
        path=self.window/'network-window.json'
        path.write_bytes(b'{')
        self.recovery()
        with patch.object(guard,'check_network') as check:
            result=guard.require_closed_windows(SimpleNamespace(root=self.root,registration=self.reg))
        self.assertEqual(result,{'machine':'recovered_closed'})
        check.assert_called_once()
        self.assertEqual(path.read_bytes(),b'{')

    def test_changed_original_invalidates_recovery(self):
        self.write(dict(self.record,phase='open',network_denied_after=False))
        self.recovery()
        self.write()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_recovery_missing_partial_or_flags_invalid_never_falls_back_to_closed(self):
        self.write()
        path,record=self.recovery()
        for raw in (b'{',json.dumps(dict(record,all_vms_stopped=1)).encode(),
                    json.dumps(dict(record,stop_removed=True)).encode(),
                    b'{"phase":"pending",'+json.dumps(record).encode()[1:]):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.inspect()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.inspect()

    def test_recovered_receipt_cannot_override_current_open_network(self):
        self.write(dict(self.record,phase='open',network_denied_after=False))
        self.recovery()
        with patch.object(guard,'check_network',side_effect=RuntimeError('still open')):
            with self.assertRaises(RuntimeError):
                guard.require_closed_windows(SimpleNamespace(root=self.root,registration=self.reg))

    def test_no_window_is_not_opened_not_auth_or_policy_acceptance(self):
        self.assertEqual(self.inspect(),{'machine':'not_opened'})

    def test_closed_journal_rechecks_current_network(self):
        self.write()
        runtime=SimpleNamespace(root=self.root,registration=self.reg)
        with patch.object(guard,'check_network') as check:
            self.assertEqual(guard.require_closed_windows(runtime),{'machine':'closed'})
        check.assert_called_once_with(runtime,'machine',stage='initial',repo=None,timeout=45)

    def test_closed_journal_does_not_override_live_network_failure(self):
        self.write()
        with patch.object(guard,'check_network',side_effect=RuntimeError('open')):
            with self.assertRaises(RuntimeError):
                guard.require_closed_windows(SimpleNamespace(root=self.root,registration=self.reg))

    def test_all_interrupted_phases_and_unknown_phase_refused(self):
        for phase in ('prepared','adding_restrictions','opening','open','inspection_required','unknown'):
            with self.subTest(phase=phase):
                self.write(dict(self.record,phase=phase))
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_partial_missing_and_duplicate_json_refused(self):
        self.window.mkdir(mode=0o700)
        with self.assertRaises(FileNotFoundError):
            self.inspect()
        self.write()
        path=self.window/'network-window.json'
        for raw in ('{','{"phase":"open",'+json.dumps(self.record)[1:]):
            path.write_text(raw)
            with self.assertRaises(ValueError):
                self.inspect()

    def test_flags_identities_and_unknown_fields_refused(self):
        for key,value in (('network_denied_after',1),('automatic_resume',0),('role','kernel'),
                          ('sandbox_id',self.epoch),('schema',True),('extra','ignored')):
            with self.subTest(key=key):
                self.write(dict(self.record,**{key:value}))
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_symlink_window_refused(self):
        other=self.root/'other'
        other.mkdir(mode=0o700)
        self.window.symlink_to(other,target_is_directory=True)
        with self.assertRaises(ValueError):
            self.inspect()

    def test_foreign_epoch_or_unknown_fence_entry_refused(self):
        self.reg['migration_epoch']=self.vm
        with self.assertRaises(ValueError):
            self.inspect()
        self.reg['migration_epoch']=self.epoch
        (self.root/'model-turn-fences'/'unexpected.json').touch()
        with self.assertRaises(ValueError):
            self.inspect()


if __name__=='__main__':
    unittest.main()

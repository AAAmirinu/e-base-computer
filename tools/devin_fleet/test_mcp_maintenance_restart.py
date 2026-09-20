import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import mcp_maintenance_restart as guard


class RestartTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/tmp'); self.addCleanup(temp.cleanup)
        self.run=Path(temp.name)/'fixed-run'
        p=patch.object(guard,'RUN',self.run); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'DISCOVERY_RUN',Path(temp.name)/'absent-discovery'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'WILDCARD_RUN',Path(temp.name)/'absent-wildcard'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'CONTROL_RUN',Path(temp.name)/'absent-control'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'COMPATIBLE_CONTROL_RUN',Path(temp.name)/'absent-compatible'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'PARAMS_CONTROL_RUN',Path(temp.name)/'absent-params'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'PREVIOUS_CONTROL_RUN',Path(temp.name)/'absent-previous-control'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'PREVIOUS_RUN',Path(temp.name)/'absent-mcp-v1'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'CATALOG_RUN',Path(temp.name)/'absent-catalog'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'PREVIOUS_CATALOG_RUN',Path(temp.name)/'absent-previous'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'SECOND_CATALOG_RUN',Path(temp.name)/'absent-second'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'THIRD_CATALOG_RUN',Path(temp.name)/'absent-third'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'FOURTH_CATALOG_RUN',Path(temp.name)/'absent-fourth'); p.start(); self.addCleanup(p.stop)
        p=patch.object(guard,'check_network'); self.check=p.start(); self.addCleanup(p.stop)
        self.runtime=SimpleNamespace(registration={'roles':{'machine':{'id':guard.MACHINE,'name':'e-base-machine'}}})

    def write(self,path,value):
        path.write_text(json.dumps(value)); path.chmod(0o600)

    def prepare(self,phase='closed'):
        self.run.mkdir(mode=0o700)
        self.write(self.run/'network-attempt.json',dict(schema=1,sandbox_id=guard.MACHINE,
                   run_directory=str(self.run),state='reserved',automatic_resume=False))
        window=self.run/'network-window'; window.mkdir(mode=0o700)
        self.write(window/'network-window.json',dict(schema=1,role='machine',sandbox_id=guard.MACHINE,
                   phase=phase,network_denied_after=phase=='closed',automatic_resume=False,created_deny_ids=[]))

    def test_absent_run_is_inert(self):
        guard.require_closed_maintenance(self.runtime); self.check.assert_not_called()

    def test_partial_run_refuses_before_policy(self):
        self.run.mkdir(mode=0o700)
        with self.assertRaises(OSError): guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_previous_catalog_partial_state_still_blocks(self):
        previous=self.run.parent/'previous'; previous.mkdir(mode=0o700)
        with patch.object(guard,'PREVIOUS_CATALOG_RUN',previous):
            with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_previous_mcp_partial_state_still_blocks(self):
        previous=self.run.parent/'mcp-v1'; previous.mkdir(mode=0o700)
        with patch.object(guard,'PREVIOUS_RUN',previous):
            with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_all_historical_paths_remain_restart_checked(self):
        with patch.object(guard,'require_closed_path') as inspect:
            guard.require_closed_maintenance(self.runtime)
        self.assertEqual([c.args[1] for c in inspect.call_args_list],
                         [guard.PREVIOUS_RUN,guard.RUN,guard.PREVIOUS_CATALOG_RUN,
                          guard.SECOND_CATALOG_RUN,guard.THIRD_CATALOG_RUN,guard.FOURTH_CATALOG_RUN,guard.CATALOG_RUN,guard.DISCOVERY_RUN,guard.WILDCARD_RUN,guard.PREVIOUS_CONTROL_RUN,guard.CONTROL_RUN,guard.COMPATIBLE_CONTROL_RUN,guard.PARAMS_CONTROL_RUN])

    def test_partial_params_reservation_blocks_restart(self):
        guard.PARAMS_CONTROL_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_partial_control_reservation_blocks_restart(self):
        guard.CONTROL_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_partial_compatible_reservation_blocks_restart(self):
        guard.COMPATIBLE_CONTROL_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_fourth_catalog_partial_state_still_blocks(self):
        guard.FOURTH_CATALOG_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_previous_control_partial_state_still_blocks(self):
        guard.PREVIOUS_CONTROL_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_partial_wildcard_reservation_blocks_restart(self):
        guard.WILDCARD_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_partial_discovery_reservation_blocks_restart(self):
        guard.DISCOVERY_RUN.mkdir(mode=0o700)
        with self.assertRaises(OSError):guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_uncertain_window_refuses(self):
        self.prepare('opening')
        with self.assertRaises(ValueError): guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_closed_receipt_still_requires_live_policy(self):
        self.prepare()
        guard.require_closed_maintenance(self.runtime)
        self.check.assert_called_once_with(self.runtime,'machine',stage='initial',repo=None,timeout=45)
        self.check.side_effect=ValueError('policy open')
        with self.assertRaisesRegex(ValueError,'policy open'): guard.require_closed_maintenance(self.runtime)

    def test_symlink_run_refused(self):
        self.run.symlink_to(self.run.parent,target_is_directory=True)
        with self.assertRaises((ValueError,OSError)): guard.require_closed_maintenance(self.runtime)
        self.check.assert_not_called()

    def test_window_change_during_live_check_rejected(self):
        self.prepare()
        self.check.side_effect=lambda *a,**k:self.write(self.run/'network-window'/'network-window.json',{})
        with self.assertRaisesRegex(ValueError,'reservation changed'):
            guard.require_closed_maintenance(self.runtime)

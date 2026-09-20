"""Stateful synthetic policy tests; no actual VM or network is touched."""
import json
import unittest
from unittest.mock import Mock,patch
import mcp_maintenance_network as window
import mcp_maintenance_restart as restart
import test_model_network_window as fixtures
import model_network_window as engine
import model_network_admission as admission
from sandbox_runtime import SandboxRuntime


class MaintenanceWindowTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ModelNetworkWindowTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.runtime=object.__new__(SandboxRuntime)
        self.runtime.__dict__.update(vars(self.f.runtime))
        self.runtime.registration['production_enabled']=False
        self.runtime.registration['roles']['machine']['id']=window.MACHINE
        self.runtime.capacity=1
        registry=self.f.root/'sandbox-registry.json'
        registry.write_text(json.dumps(self.runtime.registration)); registry.chmod(0o600)
        self.f.controller.sandbox_id=window.MACHINE
        self.run=self.f.root/'mcp-live-v2'
        self.f.directory=self.run/'network-window'
        self.repo=self.f.repo
        for module,name,value in ((window,'RUN',self.run),(restart,'RUN',self.run),
                                  (restart,'PREVIOUS_RUN',self.f.root/'mcp-live-v1'),
                                  (engine,'MCP_WINDOW',self.f.directory)):
            p=patch.object(module,name,value); p.start(); self.addCleanup(p.stop)
        for name in ('PREVIOUS_CATALOG_RUN','SECOND_CATALOG_RUN','THIRD_CATALOG_RUN','FOURTH_CATALOG_RUN','CATALOG_RUN','DISCOVERY_RUN','WILDCARD_RUN','PREVIOUS_CONTROL_RUN','CONTROL_RUN','COMPATIBLE_CONTROL_RUN','PARAMS_CONTROL_RUN'):
            p=patch.object(restart,name,self.f.root/('absent-'+name)); p.start(); self.addCleanup(p.stop)
        for name,value in (('require_managed_namespace',None),('global_lock_held',True)):
            p=patch.object(window,name,return_value=value); p.start(); self.addCleanup(p.stop)
        self.boundary=Mock()
        p=patch.object(window,'make_boundary_check',return_value=self.boundary); p.start(); self.addCleanup(p.stop)

    def enter(self): return window.machine_probe_network(self.runtime,self.repo,timeout=120)

    def test_discovery_has_distinct_one_shot_window(self):
        run=self.f.root/'mcp-discovery-live-v1'
        self.f.directory=run/'network-window'
        with patch.object(window,'DISCOVERY_RUN',run),patch.object(restart,'DISCOVERY_RUN',run),patch.object(engine,'DISCOVERY_WINDOW',self.f.directory):
            with window.discovery_probe_network(self.runtime,self.repo,timeout=120):
                self.assertTrue((run/'network-attempt.json').is_file())
                self.assertFalse(self.run.exists())
                admission.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30,catalog_access=True)
            self.f.assert_closed()
            restart.require_closed_maintenance(self.runtime)
            with self.assertRaises(FileExistsError):
                with window.discovery_probe_network(self.runtime,self.repo,timeout=120):self.fail('Reentry')

    def test_wildcard_has_distinct_one_shot_window(self):
        run=self.f.root/'mcp-wildcard-live-v1'
        self.f.directory=run/'network-window'
        with patch.object(window,'WILDCARD_RUN',run),patch.object(restart,'WILDCARD_RUN',run),patch.object(engine,'WILDCARD_WINDOW',self.f.directory):
            with window.wildcard_probe_network(self.runtime,self.repo,timeout=120):
                self.assertTrue((run/'network-attempt.json').is_file())
                self.assertFalse(self.run.exists())
                admission.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30,catalog_access=True)
            self.f.assert_closed()
            restart.require_closed_maintenance(self.runtime)
            with self.assertRaises(FileExistsError):
                with window.wildcard_probe_network(self.runtime,self.repo,timeout=120):self.fail('Reentry')

    def test_opens_restores_and_refuses_second_attempt(self):
        with self.enter() as remaining:
            self.assertGreater(remaining,0)
            self.assertTrue((self.run/'network-attempt.json').is_file())
            self.assertEqual(self.f.receipt()['phase'],'open')
            admission.check_network(self.runtime,'machine',stage='before_model',
                                    repo=self.repo,timeout=30,catalog_access=True)
            with self.assertRaises(ValueError):
                admission.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30)
        self.f.assert_closed()
        count=len(self.f.events)
        with self.assertRaises(FileExistsError),self.enter(): self.fail('Repeated attempt')
        self.assertEqual(len(self.f.events),count)
        restart.require_closed_maintenance(self.runtime)

    def test_control_distinct_window_and_exception_restoration(self):
        run=self.f.root/'mcp-echo-control-live-v2'
        self.f.directory=run/'network-window'
        with patch.object(window,'CONTROL_RUN',run),patch.object(restart,'CONTROL_RUN',run),patch.object(engine,'CONTROL_WINDOW',self.f.directory):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):
                with window.echo_control_network(self.runtime,self.repo,timeout=120):
                    self.assertTrue((run/'network-attempt.json').is_file())
                    self.assertFalse(self.run.exists())
                    admission.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30,catalog_access=True)
                    raise RuntimeError('synthetic')
            self.f.assert_closed()
            restart.require_closed_maintenance(self.runtime)

    def test_control_completed_window_reentry_refused(self):
        run=self.f.root/'mcp-echo-control-live-v2';self.f.directory=run/'network-window'
        with patch.object(window,'CONTROL_RUN',run),patch.object(restart,'CONTROL_RUN',run),patch.object(engine,'CONTROL_WINDOW',self.f.directory):
            with window.echo_control_network(self.runtime,self.repo,timeout=120):pass
            self.f.assert_closed()
            count=len(self.f.events)
            with self.assertRaises(FileExistsError):
                with window.echo_control_network(self.runtime,self.repo,timeout=120):self.fail('Reentry')
            self.assertEqual(len(self.f.events),count)
            restart.require_closed_maintenance(self.runtime)

    def test_old_mcp_window_cannot_be_reused(self):
        old=self.f.root/'mcp-live-v1'
        with self.assertRaises(ValueError):
            with window._reserved_network(self.runtime,self.repo,timeout=120,run=old):
                self.fail('Old MCP attempt reused')
        self.assertEqual(self.f.events,[])

    def test_compatible_window_closes_and_refuses_reentry(self):
        run=self.f.root/'mcp-echo-compatible-live-v1';self.f.directory=run/'network-window'
        with patch.object(window,'COMPATIBLE_CONTROL_RUN',run),patch.object(restart,'COMPATIBLE_CONTROL_RUN',run),patch.object(engine,'COMPATIBLE_CONTROL_WINDOW',self.f.directory):
            with window.compatible_control_network(self.runtime,self.repo,timeout=120):
                admission.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30,catalog_access=True)
            self.f.assert_closed()
            count=len(self.f.events)
            with self.assertRaises(FileExistsError):
                with window.compatible_control_network(self.runtime,self.repo,timeout=120):self.fail('Reentry')
            self.assertEqual(len(self.f.events),count)
            restart.require_closed_maintenance(self.runtime)

    def test_compatible_exception_restores_denial(self):
        run=self.f.root/'mcp-echo-compatible-live-v1';self.f.directory=run/'network-window'
        with patch.object(window,'COMPATIBLE_CONTROL_RUN',run),patch.object(restart,'COMPATIBLE_CONTROL_RUN',run),patch.object(engine,'COMPATIBLE_CONTROL_WINDOW',self.f.directory):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):
                with window.compatible_control_network(self.runtime,self.repo,timeout=120):
                    raise RuntimeError('synthetic')
            self.f.assert_closed()
            restart.require_closed_maintenance(self.runtime)

    def test_standalone_feature_denial_is_restored(self):
        self.f.rows.append(dict(self.f.rows[1],id='feature',resources=[admission.FEATURE_HOST]))
        with self.enter():
            self.assertFalse(any(r['decision']=='deny' and admission.FEATURE_HOST in r['resources']
                                 for r in self.f.rows))
        self.f.assert_closed()
        self.assertTrue(any(r['decision']=='deny' and r['resources']==[admission.FEATURE_HOST]
                            for r in self.f.rows))
        self.assertEqual([event for event in self.f.events if event[0]=='rm'],
                         [('rm','feature'),('rm','owned')])

    def test_params_window_closes_and_refuses_reentry(self):
        run=self.f.root/'mcp-echo-params-live-v1';self.f.directory=run/'network-window'
        with patch.object(window,'PARAMS_CONTROL_RUN',run),patch.object(restart,'PARAMS_CONTROL_RUN',run),patch.object(engine,'PARAMS_CONTROL_WINDOW',self.f.directory):
            with window.params_control_network(self.runtime,self.repo,timeout=120):
                admission.check_network(self.runtime,'machine',stage='before_model',repo=self.repo,timeout=30,catalog_access=True)
            self.f.assert_closed()
            count=len(self.f.events)
            with self.assertRaises(FileExistsError):
                with window.params_control_network(self.runtime,self.repo,timeout=120):self.fail('Reentry')
            self.assertEqual(len(self.f.events),count)
            restart.require_closed_maintenance(self.runtime)

    def test_params_exception_restores_denial(self):
        run=self.f.root/'mcp-echo-params-live-v1';self.f.directory=run/'network-window'
        with patch.object(window,'PARAMS_CONTROL_RUN',run),patch.object(restart,'PARAMS_CONTROL_RUN',run),patch.object(engine,'PARAMS_CONTROL_WINDOW',self.f.directory):
            with self.assertRaisesRegex(RuntimeError,'synthetic'):
                with window.params_control_network(self.runtime,self.repo,timeout=120):
                    raise RuntimeError('synthetic')
            self.f.assert_closed()
            restart.require_closed_maintenance(self.runtime)

    def test_params_deadline_restores_denial(self):
        run=self.f.root/'mcp-echo-params-live-v1';self.f.directory=run/'network-window'
        with patch.object(window,'PARAMS_CONTROL_RUN',run),patch.object(restart,'PARAMS_CONTROL_RUN',run),patch.object(engine,'PARAMS_CONTROL_WINDOW',self.f.directory):
            with patch.object(window.time,'monotonic',return_value=100) as clock:
                with self.assertRaisesRegex(RuntimeError,'deadline'):
                    with window.params_control_network(self.runtime,self.repo,timeout=120):clock.return_value=500
            self.f.assert_closed()
            self.assertTrue(self.runtime._failed)
            restart.require_closed_maintenance(self.runtime)

    def test_reservation_write_failure_has_no_policy_operations(self):
        with patch.object(window,'_exclusive_file',side_effect=OSError('disk failed')):
            with self.assertRaises(OSError),self.enter(): self.fail('Write failure ignored')
        self.assertEqual(self.f.events,[])
        self.assertTrue(self.run.exists())
        self.f.controller.stop.assert_called_once()
        with self.assertRaises(OSError): restart.require_closed_maintenance(self.runtime)

    def test_params_production_rejected_before_reservation(self):
        run=self.f.root/'mcp-echo-params-live-v1';self.f.directory=run/'network-window'
        self.runtime.registration['production_enabled']=True
        with patch.object(window,'PARAMS_CONTROL_RUN',run),patch.object(engine,'PARAMS_CONTROL_WINDOW',self.f.directory):
            with self.assertRaises(ValueError):
                with window.params_control_network(self.runtime,self.repo,timeout=120):self.fail('Production admitted')
        self.assertFalse(run.exists())
        self.assertEqual(self.f.events,[])

    def test_uncertain_removal_restores_and_retains_reservation(self):
        self.f.failure='remove'
        with self.assertRaises(RuntimeError),self.enter(): self.fail('Uncertain mutation ignored')
        self.f.assert_closed()
        self.assertTrue((self.run/'network-attempt.json').is_file())
        self.assertTrue(self.runtime._failed)

    def test_body_failure_closes_before_stop(self):
        with self.assertRaisesRegex(RuntimeError,'body'):
            with self.enter(): raise RuntimeError('body')
        self.f.assert_closed()
        self.f.controller.stop.assert_called_once()

    def test_cleanup_failure_blocks_next_runtime(self):
        with self.assertRaises(RuntimeError):
            with self.enter(): self.f.failure='close'
        self.assertEqual(self.f.receipt()['phase'],'inspection_required')
        self.assertTrue(self.f.controller.stop.called)
        with self.assertRaises(ValueError): restart.require_closed_maintenance(self.runtime)

    def test_unlocked_or_foreign_lease_refused(self):
        with patch.object(window,'global_lock_held',return_value=False):
            with self.assertRaises(ValueError),self.enter(): self.fail('Unlocked admitted')
        self.f.controller.sandbox_id='other'
        with self.assertRaises(ValueError),self.enter(): self.fail('Wrong VM admitted')
        self.assertEqual(self.f.events,[])
        self.assertFalse(self.run.exists())

    def test_wrong_root_and_production_refused(self):
        original=self.runtime.root
        self.runtime.root=original/'other'
        with self.assertRaises(ValueError),self.enter(): self.fail('Wrong root admitted')
        self.runtime.root=original
        self.runtime.registration['production_enabled']=True
        with self.assertRaises(ValueError),self.enter(): self.fail('Production admitted')
        self.assertEqual(self.f.events,[])

    def test_boundary_failure_precedes_reservation_and_network(self):
        self.boundary.side_effect=ValueError('boundary')
        with self.assertRaises(ValueError),self.enter(): self.fail('Boundary ignored')
        self.assertFalse(self.run.exists())
        self.assertEqual(self.f.events,[])

    def test_deadline_after_body_still_closes(self):
        with patch.object(window.time,'monotonic',return_value=100) as clock:
            with self.assertRaisesRegex(RuntimeError,'deadline'):
                with self.enter(): clock.return_value=500
        self.f.assert_closed()
        self.assertTrue(self.runtime._failed)

    def test_registration_change_during_boundary_refused(self):
        self.boundary.side_effect=lambda *a,**k:(self.f.root/'sandbox-registry.json').write_text('{}')
        with self.assertRaises(ValueError),self.enter(): self.fail('Changed registration admitted')
        self.assertFalse(self.run.exists())
        self.assertEqual(self.f.events,[])


if __name__=='__main__': unittest.main()

import json
import unittest
from unittest.mock import patch
import inspect_mcp_result as inspection


class InspectionTests(unittest.TestCase):
    def test_compatible_snapshot_uses_fixed_new_state(self):
        source='def summarize(*args): return {}\ndef validate(v): return v\n'
        with patch.object(inspection,'_file',return_value=source.encode()):
            command=inspection.control_probe(source,source.encode(),compatible=True)
        compile(command,'<compatible-diagnostic>','exec')
        self.assertIn('prepare.STATE=prepare.COMPATIBLE_CONTROL_STATE',command)
        self.assertIn('inspect.inspect_compatible_control',command)

    def test_compatible_conflicts_refused_before_namespace(self):
        for args in (dict(compatible=1),dict(compatible=True,control=True),dict(compatible=True,discovery=True),dict(compatible=True,wildcard=True)):
            with patch.object(inspection,'require_managed_namespace') as guard:
                with self.assertRaises(ValueError):inspection.main(**args)
                guard.assert_not_called()

    def test_control_fixed_snapshot_bootstrap(self):
        source='def summarize(*args): return {}\ndef validate(v): return v\n'
        with patch.object(inspection,'_file',return_value=source.encode()):
            command=inspection.control_probe(source,source.encode())
        compile(command,'<control-diagnostic>','exec')
        self.assertIn('prepare.STATE=prepare.CONTROL_STATE',command)
        self.assertEqual(command.count("print('EBASE_MCP_RESULT_SUMMARY:'"),1)
        self.assertIn("captured['export_raw']",command)

    def test_control_conflicts_refused_before_namespace(self):
        for args in (dict(control=1),dict(control=True,discovery=True),dict(control=True,wildcard=True)):
            with patch.object(inspection,'require_managed_namespace') as guard:
                with self.assertRaises(ValueError):inspection.main(**args)
                guard.assert_not_called()

    def test_wildcard_bootstrap_reads_captured_snapshot_only(self):
        source='def summarize(*args): return {}\ndef validate(v): return v\n'
        with patch.object(inspection,'_file',return_value=source.encode()):
            command=inspection.wildcard_probe(source,source.encode())
        compile(command,'<wildcard-diagnostic>','exec')
        self.assertIn('prepare.STATE=prepare.WILDCARD_STATE',command)
        self.assertEqual(command.count("print('EBASE_MCP_RESULT_SUMMARY:'"),1)
        self.assertIn("captured['export_raw']",command)

    def test_conflicting_inspection_kind_refused(self):
        with patch.object(inspection,'require_managed_namespace') as guard:
            with self.assertRaises(ValueError):inspection.main(discovery=True,wildcard=True)
            guard.assert_not_called()

    def test_discovery_bootstrap_is_collect_followed_by_shape_only(self):
        source='def summarize(*args): return {}\ndef validate(v): return v\n'
        with patch.object(inspection,'_file',return_value=source.encode()):
            command=inspection.discovery_probe(source,source.encode())
        compile(command,'<discovery-shape>','exec')
        self.assertEqual(command.count("print('EBASE_MCP_DISPATCH:'"),1)
        self.assertEqual(command.count("print('EBASE_MCP_RESULT_SUMMARY:'"),1)
        self.assertIn("captured['export_raw']",command)

    def test_classifier_is_captured_source_not_reread(self):
        source='def summarize(*args): return {}\ndef validate(v): return v\n'
        captured=b'# captured classifier\n'
        with patch.object(inspection,'_file',return_value=source.encode()) as read:
            command=inspection.discovery_probe(source,captured)
        self.assertIn('# captured classifier',command)
        self.assertEqual(read.call_count,1)
        self.assertEqual(read.call_args.args[0],inspection.ROOT/'mcp_discovery_inputs.py')

    def test_bootstrap_preserves_readonly_collect_and_compiles(self):
        source='def summarize(*args): return {}\ndef validate(v): return v\n'
        command=inspection.probe(source)
        self.assertTrue(command.startswith(inspection.PROBE+'\n'))
        compile(command,'<diagnostic>','exec')
        suffix=command[len(inspection.PROBE):]
        self.assertNotIn('launch_reserved',suffix)
        self.assertNotIn('subprocess',suffix)
        self.assertIn("stage='after'",suffix)
        self.assertIn("result['export_sha256']",suffix)

    def test_foreign_receipt_refuses_before_vm(self):
        reg={'production_enabled':False,'roles':{'machine':{'id':inspection.MACHINE}}}
        for receipt in ({},dict(phase='complete',all_vms_stopped=False)):
            with self.subTest(receipt=receipt),patch.object(inspection,'require_managed_namespace'),patch.object(
                    inspection,'_file',side_effect=[json.dumps(reg).encode(),json.dumps(receipt).encode()]),patch.object(
                    inspection,'SandboxRuntime') as runtime:
                with self.assertRaises(ValueError):inspection.main()
                runtime.assert_not_called()


if __name__=='__main__':unittest.main()

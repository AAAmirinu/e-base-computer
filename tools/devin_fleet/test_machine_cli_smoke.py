"""Mock-only one-shot inference gates: no VM, CLI, network or filesystem writes."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

import machine_cli_smoke as smoke


class MachineCliSmokeTests(unittest.TestCase):
    def run_smoke(self, *, expired=False, free=True, duplicate=False, model=None,
                  steps=None):
        marker, work = MagicMock(), MagicMock()
        marker.parent = 'mock-parent'
        if duplicate:
            marker.open.side_effect = FileExistsError('already reserved')
        marker.open.return_value.__enter__.return_value.fileno.return_value = 42
        paths = {}
        def child(name):
            paths.setdefault(name, MagicMock())
            paths[name].__str__.return_value = '/mock/' + name
            return paths[name]
        work.__truediv__.side_effect = child
        payload = {'steps': steps if steps is not None else [
            {'source': 'agent', 'model_name': model or smoke.MODEL}]}
        child('export.json').read_bytes.return_value = json.dumps(payload).encode()
        catalog = {'families': [{'variants': [
            {'model_uid': smoke.MODEL, 'cost_tier': 'Free' if free else 'Paid'}]}]}
        proc = MagicMock(returncode=0)
        proc.communicate.return_value = (b'EBASE_SWE2_OK', b'')
        with ExitStack() as stack:
            clock = stack.enter_context(patch.object(smoke, 'datetime'))
            clock.now.return_value = (smoke.EXPIRY if expired else
                                     datetime(2026, 9, 19, tzinfo=timezone.utc))
            run = stack.enter_context(patch.object(smoke.subprocess, 'run'))
            run.return_value.stdout = json.dumps(catalog).encode()
            popen = stack.enter_context(patch.object(smoke.subprocess, 'Popen', return_value=proc))
            stack.enter_context(patch.object(smoke, 'Path', side_effect=[marker, work]))
            stack.enter_context(patch.object(smoke.tempfile, 'mkdtemp', return_value='/mock'))
            stack.enter_context(patch.object(smoke.os, 'open', return_value=43))
            stack.enter_context(patch.object(smoke.os, 'fsync'))
            stack.enter_context(patch.object(smoke.os, 'close'))
            stack.enter_context(patch.object(smoke.os, 'O_DIRECTORY', 0, create=True))
            output = stack.enter_context(patch('builtins.print'))
            smoke.main()
            result = json.loads(output.call_args.args[0])
        return result, run, popen, marker, paths

    def test_expired_before_catalog_or_inference(self):
        result, run, popen, marker, _ = self.run_smoke(expired=True)
        self.assertFalse(result['passed'])
        self.assertIs(result['model_executed'], False)
        run.assert_not_called()
        popen.assert_not_called()
        marker.open.assert_not_called()

    def test_paid_catalog_before_reservation_or_inference(self):
        result, run, popen, marker, _ = self.run_smoke(free=False)
        self.assertFalse(result['passed'])
        run.assert_called_once()
        popen.assert_not_called()
        marker.open.assert_not_called()

    def test_duplicate_marker_blocks_inference(self):
        result, _, popen, marker, _ = self.run_smoke(duplicate=True)
        self.assertFalse(result['passed'])
        self.assertEqual(result['error_type'], 'FileExistsError')
        marker.open.assert_called_once_with('x')
        popen.assert_not_called()

    def test_happy_path_is_one_exact_model_normal_invocation(self):
        result, _, popen, _, paths = self.run_smoke()
        self.assertTrue(result['passed'])
        self.assertTrue(result['exact_model_verified'])
        self.assertTrue(result['raw_output_suppressed'])
        popen.assert_called_once()
        args = popen.call_args.args[0]
        self.assertEqual(args[0], smoke.CLI)
        self.assertEqual(args[args.index('--model') + 1], 'swe-2-high')
        self.assertEqual(args[args.index('--permission-mode') + 1], 'normal')
        self.assertNotIn('--resume', args)
        self.assertEqual(popen.call_args.kwargs['stdin'], smoke.subprocess.DEVNULL)
        config = json.loads(paths['config.json'].write_text.call_args.args[0])
        self.assertEqual(config['permissions']['allow'], [])

    def test_other_model_cannot_pass(self):
        result, _, popen, _, _ = self.run_smoke(model='other-model')
        popen.assert_called_once()
        self.assertFalse(result['passed'])
        self.assertFalse(result['exact_model_verified'])

    def test_observed_display_name_passes(self):
        result, _, _, _, _ = self.run_smoke(model='SWE-2 High')
        self.assertTrue(result['passed'])

    def test_separate_tool_step_fails(self):
        result, _, _, _, _ = self.run_smoke(steps=[
            {'source': 'agent', 'model_name': smoke.MODEL}, {'source': 'tool'}])
        self.assertFalse(result['passed'])

    def test_agent_tool_call_cannot_pass(self):
        result, _, _, _, _ = self.run_smoke(steps=[
            {'source': 'agent', 'model_name': smoke.MODEL, 'tool_calls': [{'name': 'exec'}]}])
        self.assertFalse(result['passed'])
        self.assertFalse(result['no_tool_calls'])


if __name__ == '__main__':
    unittest.main()

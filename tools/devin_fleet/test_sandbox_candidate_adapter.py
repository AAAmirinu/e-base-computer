"""Synthetic build/import adapter integration; runner never starts a VM."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sandbox_candidate_adapter as adapter
import test_candidate_evidence_binding as fixtures


def sha(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(os.name == 'posix', 'Private controller files')
class SandboxCandidateAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.fixture = fixtures.TurnCandidateBindingTests()
        self.fixture.setUp()
        f = self.fixture
        f.validator, f.image = adapter.UUID, adapter.runner.IMAGE
        f.dispatch.update(sandbox_id=f.validator, image_id=f.image)
        f.summary['receipt']['image_id'] = f.image
        for item in (f.build, f.imported):
            item['image_id'] = f.image
            item['container_evidence']['image_id'] = f.image
        self.patch(adapter.runner, 'ROOT', self.root)
        self.patch(adapter, 'require_managed_namespace')
        self.admission = Mock()
        self.patch(adapter, 'make_admission', return_value=self.admission)
        self.execute = self.patch(adapter.runner, 'execute', side_effect=self.run_candidate)
        self.locations = []
        self.lifecycle_changes = {}
        self.import_bundle = None
        self.guest_changes = {}
        for module in adapter.MODULES:
            (self.root / (module + '.py')).write_text('# inert synthetic controller module\n')

    def patch(self, owner, name, *args, **kwargs):
        context = patch.object(owner, name, *args, **kwargs)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def evidence(self):
        values = self.fixture.packet()
        return {key: value for key, value in values.items() if key not in ('build_raw', 'import_raw', 'bundle')}

    def run_candidate(self, packet, work, *, admission):
        self.assertIs(admission, self.admission)
        work.mkdir(mode=0o700)
        self.locations.append(work)
        imported = json.loads(packet).get('verify_import') is True
        source = self.fixture.imported if imported else self.fixture.build
        guest = copy.deepcopy(source['container_evidence'])
        bundle = self.import_bundle if imported and self.import_bundle is not None else self.fixture.bundle
        guest['candidate'] = dict(metadata=copy.deepcopy(source['candidate']),
                                  bundle=base64.b64encode(bundle).decode())
        guest.update(self.guest_changes)
        raw = json.dumps(guest).encode()
        (work / 'stdout.json').write_bytes(raw)
        receipt = dict(phase='stopped_result', all_vms_stopped=True, image_id=adapter.runner.IMAGE,
                       packet_sha256=sha(packet), stdout_sha256=sha(raw))
        receipt.update(self.lifecycle_changes)
        (work / 'receipt.json').write_text(json.dumps(receipt))
        return dict(directory=str(work), guest=guest)

    def invoke(self):
        parent = b'synthetic trusted parent bundle'
        return adapter.build_and_import(self.fixture.turn_binding, self.evidence(),
            registration=self.fixture.registration, parent_bundle=parent,
            parent_bundle_sha256=sha(parent), parent_ref='refs/heads/fleet/integration')

    def test_two_distinct_attempts_return_fully_bound_raw_evidence(self):
        built = self.invoke()
        self.assertEqual(self.execute.call_count, 2)
        self.assertEqual(len(set(self.locations)), 2)
        self.assertEqual(set(built), {'build_raw', 'import_raw', 'bundle'})
        self.assertEqual(built['bundle'], self.fixture.bundle)
        build, imported = json.loads(built['build_raw']), json.loads(built['import_raw'])
        self.assertEqual(imported['origin_receipt_sha256'], sha(built['build_raw']))
        self.assertNotEqual(build['container_evidence']['container_id'], imported['container_evidence']['container_id'])
        self.admission.assert_called_once_with()
        for location in self.locations:
            self.assertTrue((location / 'candidate.json').is_file())
            self.assertEqual((location / 'candidate.bundle').read_bytes(), built['bundle'])

    def test_explicit_admission_factory_is_bound(self):
        parent=b'synthetic trusted parent bundle'
        with self.assertRaisesRegex(ValueError,'production or fixed prepared-trial'):
            adapter.build_and_import(self.fixture.turn_binding,self.evidence(),
                registration=self.fixture.registration,parent_bundle=parent,
                parent_bundle_sha256=sha(parent),parent_ref='refs/heads/fleet/integration',
                admission_factory=lambda registration, binding: self.admission)

    def test_retry_reuses_identity_and_exclusive_reservation_refuses(self):
        self.invoke()
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(len(self.locations), 2)
        self.assertEqual(self.execute.call_args.args[1], self.locations[0])

    def test_failed_validation_does_not_start_candidate_attempt(self):
        self.fixture.summary['receipt']['test']['returncode'] = 1
        self.fixture.summary['receipt']['test_command_succeeded'] = False
        self.fixture.dispatch.update(returncode=1, phase='inspection_required')
        with self.assertRaises(ValueError):
            self.invoke()
        self.execute.assert_not_called()

    def test_import_must_return_identical_bundle(self):
        self.import_bundle = b'different bundle'
        with self.assertRaisesRegex(ValueError, 'different bundle'):
            self.invoke()
        self.assertEqual(self.execute.call_count, 2)

    def test_lifecycle_packet_digest_tampering_rejected_before_import(self):
        self.lifecycle_changes['packet_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.execute.call_count, 1)

    def test_lifecycle_stdout_digest_tampering_rejected_before_import(self):
        self.lifecycle_changes['stdout_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.execute.call_count, 1)

    def test_lifecycle_stop_failure_rejected_before_import(self):
        self.lifecycle_changes['all_vms_stopped'] = False
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.execute.call_count, 1)

    def test_distinct_container_requirement_is_rechecked_by_real_binder(self):
        self.fixture.imported['container_evidence']['container_id'] = self.fixture.build['container_evidence']['container_id']
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.execute.call_count, 2)

    def test_runner_exception_is_not_retried(self):
        self.execute.side_effect = RuntimeError('synthetic executor failure')
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.execute.assert_called_once()


if __name__ == '__main__':
    unittest.main()

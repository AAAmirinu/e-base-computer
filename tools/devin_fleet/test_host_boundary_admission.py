import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from host_boundary_admission import check_host_boundary
from host_boundary_contract import FIELDS

DIGEST = 'sha256:'+'a'*64


class LiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.mutate = lambda argv, value: value
        self.runtime = SimpleNamespace(registration={'roles': {'machine': {'name': 'e-base-machine'}}},
                                       transport=SimpleNamespace(control=self.control))
        self.guard = patch('host_boundary_admission.require_managed_namespace')
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def control(self, argv, timeout):
        self.calls.append(argv)
        if argv[1] == 'settings': value = False
        elif argv[1] == 'mcp': value = {'servers': [], 'gateway': dict(
            decision='local',local=True,name='local',operator='local',signed_in_as=None)}
        else:
            value = dict.fromkeys(FIELDS)
            value.update(name='e-base-machine',agent='devin',image='docker/sandbox-templates:devin-docker',
                         image_digest=DIGEST,kits=[],runtime_mounts=[])
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.mutate(argv, value)))

    def check(self, **args):
        return check_host_boundary(self.runtime, 'machine', image_digest=DIGEST, timeout=args.get('timeout',30))

    def test_live_two_pass_read_only(self):
        self.assertIsNone(self.check())
        self.assertEqual(len(self.calls), 8)
        self.assertEqual({c[1] for c in self.calls}, {'settings', 'mcp', 'inspect'})

    def test_second_pass_share_change_rejected(self):
        def mutate(argv,value):
            if argv[1]=='inspect' and len(self.calls)>4: value['runtime_mounts']=[{}]
            return value
        self.mutate=mutate
        with self.assertRaises(ValueError): self.check()

    def test_mcp_or_setting_change_rejected(self):
        for target in ('mcp','settings'):
            self.mutate=lambda argv,value: ({'servers':[{}],'gateway':{}} if target=='mcp' else True) if argv[1]==target else value
            with self.assertRaises(ValueError): self.check()

    def test_timeout_preflight(self):
        for timeout in (True,0,float('inf'),float('nan')):
            with self.assertRaises(ValueError): self.check(timeout=timeout)
        self.assertEqual(self.calls,[])

    def test_bad_return_code(self):
        self.runtime.transport.control=lambda *args: SimpleNamespace(returncode=1,stdout='private')
        with self.assertRaises(RuntimeError): self.check()


if __name__=='__main__': unittest.main()

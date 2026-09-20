import unittest
from host_boundary_contract import FIELDS, validate_host_contract

DIGEST = 'sha256:'+'a'*64


class HostContractTests(unittest.TestCase):
    def fixture(self):
        value = dict.fromkeys(FIELDS)
        value.update(name='e-base-machine', agent='devin', image='docker/sandbox-templates:devin-docker',
                     image_digest=DIGEST, runtime_mounts=[], kits=[])
        return value

    def check(self, value, **updates):
        args = dict(name='e-base-machine', image_digest=DIGEST, ssh_enabled=False,
                    clipboard_enabled=False, mcp={'servers': [], 'gateway': dict(
                        decision='local',local=True,name='local',operator='local',signed_in_as=None)})
        args.update(updates)
        return validate_host_contract(value, **args)

    def test_known_contract(self):
        self.assertIsNone(self.check(self.fixture()))

    def test_running_uptime_is_not_an_admission_signal(self):
        value=self.fixture()
        value['uptime']='observational-only'
        self.assertIsNone(self.check(value))
        value['runtime_mounts']=[{}]
        with self.assertRaises(ValueError): self.check(value)

    def test_missing_unknown_fields(self):
        value = self.fixture()
        value['unexpected'] = True
        with self.assertRaises(ValueError): self.check(value)
        value = self.fixture()
        value.pop('runtime_mounts')
        with self.assertRaises(ValueError): self.check(value)

    def test_shares_or_kits_rejected(self):
        for key in ('runtime_mounts', 'kits'):
            for item in ([{}], None, {}):
                value = self.fixture()
                value[key] = item
                with self.assertRaises(ValueError): self.check(value)

    def test_identity_changes(self):
        for key in ('name', 'agent', 'image', 'image_digest'):
            value = self.fixture()
            value[key] = 'changed'
            with self.assertRaises(ValueError): self.check(value)

    def test_ambiguous_settings_rejected(self):
        for key in ('ssh_enabled', 'clipboard_enabled'):
            for item in (0, None, True, 'false'):
                with self.assertRaises(ValueError): self.check(self.fixture(), **{key:item})

    def test_mcp_registration_rejected(self):
        for value in ({}, [], {'servers':None,'gateway':{}},
                      {'servers':[{}],'gateway':{}}, {'servers':[],'gateway':{},'extra':True}):
            with self.assertRaises(ValueError): self.check(self.fixture(), mcp=value)

    def test_digest_must_be_explicit(self):
        for value in (None, '', 'tag', 'sha256:'+'A'*64):
            with self.assertRaises(ValueError): self.check(self.fixture(), image_digest=value)

    def test_gateway_routing_not_permission_decision(self):
        for decision in ('allow', 'deny', 'remote', '', None):
            gateway = dict(decision=decision, local=True, name='local',operator='local',signed_in_as=None)
            with self.assertRaises(ValueError):
                self.check(self.fixture(), mcp={'servers':[], 'gateway':gateway})
        for gateway in (None, {}, {'decision':'local','local':True}):
            with self.assertRaises(ValueError):
                self.check(self.fixture(), mcp={'servers':[], 'gateway':gateway})


if __name__ == '__main__':
    unittest.main()

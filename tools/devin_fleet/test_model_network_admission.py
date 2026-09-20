"""Synthetic network policy evidence; no sbx, VM, or network execution."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import model_network_admission as policy


def rules(model_access=False):
    common = dict(resource_type='network', scope='sandbox:e-base-machine',
                  applies_to='sandbox:e-base-machine', status='active')
    return [dict(common, id='kit', editable=False, decision='allow', resources=sorted(policy.KIT_HOSTS)),
            dict(common, id='owned', editable=True, decision='deny',
                 resources=sorted((policy.KIT_HOSTS - policy.MODEL_HOSTS)|policy.DENY_ONLY_HOSTS) if model_access else ['**'])]


class ModelNetworkAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.rows = rules()
        self.model_access = False
        self.after = None
        self.list_count = 0
        self.allowed_override = None
        self.returncode = None
        self.runtime = SimpleNamespace(registration={'roles': {'machine': {'name': 'e-base-machine'}}},
                                       transport=SimpleNamespace(control=Mock(side_effect=self.query)))
        context = patch.object(policy, 'require_managed_namespace')
        self.guard = context.start()
        self.addCleanup(context.stop)

    def query(self, argv, timeout):
        self.assertEqual(argv[0:2], ['/usr/bin/sbx', 'policy'])
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 10)
        if argv[2] == 'ls':
            self.list_count += 1
            self.assertEqual(argv, ['/usr/bin/sbx', 'policy', 'ls', 'e-base-machine', '--json'])
            rows = self.after if self.after is not None and self.list_count > 1 else self.rows
            result, code = {'rules': rows}, 0
        else:
            self.assertEqual(argv[:7], ['/usr/bin/sbx', 'policy', 'check', 'network',
                                       '--sandbox', 'e-base-machine', '--json'])
            allowed = self.model_access and argv[-1] in policy.MODEL_HOSTS
            if self.allowed_override is not None:
                allowed = self.allowed_override
            result, code = {'allowed': allowed}, 0 if allowed is True else 1
        return SimpleNamespace(returncode=code if self.returncode is None else self.returncode,
                               stdout=json.dumps(result))

    def invoke(self, stage='initial', timeout=30):
        return policy.check_network(self.runtime, 'machine', stage=stage, repo=None, timeout=timeout)

    def test_closed_policy_checks_all_endpoints_using_read_only_argv(self):
        self.assertIsNone(self.invoke())
        calls = self.runtime.transport.control.call_args_list
        self.assertEqual(len(calls), 2 + len(policy.KIT_HOSTS|policy.DENY_ONLY_HOSTS) + len(policy.NEGATIVE_HOSTS))
        checked = [call.args[0][-1] for call in calls if call.args[0][2] == 'check']
        self.assertEqual(checked, sorted(policy.KIT_HOSTS|policy.DENY_ONLY_HOSTS) + list(policy.NEGATIVE_HOSTS))
        self.assertTrue(all(call.args[0][2] in ('ls', 'check') for call in calls))

    def test_exact_three_model_hosts_are_open_only_for_model_stage(self):
        self.model_access = True
        self.rows = rules(True)
        self.assertIsNone(self.invoke('before_model'))
        with self.assertRaises(ValueError):
            self.invoke('before_inspection')

    def test_closed_policy_does_not_admit_model_stage(self):
        with self.assertRaises(ValueError):
            self.invoke('before_model')

    def test_telemetry_is_deny_only_and_required_before_model(self):
        self.assertFalse(policy.DENY_ONLY_HOSTS & policy.KIT_HOSTS)
        changed=rules(True)
        changed[1]['resources']=[h for h in changed[1]['resources'] if h not in policy.DENY_ONLY_HOSTS]
        with self.assertRaises(ValueError):
            policy.validate_rules(changed,'e-base-machine',model_access=True)
        changed=rules(True)
        changed[0]['resources'].extend(policy.DENY_ONLY_HOSTS)
        with self.assertRaises(ValueError):
            policy.validate_rules(changed,'e-base-machine',model_access=True)

    def test_closed_legacy_state_and_retained_telemetry_denial_are_valid(self):
        for retained in (False,True):
            changed=rules()
            if retained:
                changed.append(dict(changed[1],id='telemetry',resources=sorted(policy.DENY_ONLY_HOSTS)))
            policy.validate_rules(changed,'e-base-machine',model_access=False)

    def test_wildcard_or_extra_endpoint_allow_rejected(self):
        for host in ('**', '*.devin.ai:443', 'unknown.example:443'):
            with self.subTest(host=host):
                changed = rules()
                changed[0]['resources'].append(host)
                with self.assertRaises(ValueError):
                    policy.validate_rules(changed, 'e-base-machine', model_access=False)

    def test_missing_deny_or_incomplete_kit_allow_set_rejected(self):
        missing_allow = rules()
        missing_allow[0]['resources'].pop()
        for changed in (rules()[:1], missing_allow):
            with self.subTest(rows=changed), self.assertRaises(ValueError):
                policy.validate_rules(changed, 'e-base-machine', model_access=False)

    def test_model_scope_requires_all_other_kit_endpoints_denied(self):
        changed = rules(True)
        changed[1]['resources'].pop()
        with self.assertRaises(ValueError):
            policy.validate_rules(changed, 'e-base-machine', model_access=True)

    def test_unknown_scope_status_and_duplicate_resources_rejected(self):
        for field, value in (('scope', 'global'), ('applies_to', 'sandbox:e-base-stdlib'),
                             ('status', 'inactive'), ('decision', 'unknown'),
                             ('resources', ['**', '**'])):
            with self.subTest(field=field):
                changed = rules()
                changed[1][field] = value
                with self.assertRaises(ValueError):
                    policy.validate_rules(changed, 'e-base-machine', model_access=False)

    def test_changed_editable_rule_identity_rejected_after_checks(self):
        self.after = copy.deepcopy(self.rows)
        self.after[1]['id'] = 'changed-owned-rule'
        with self.assertRaisesRegex(ValueError, 'changed during admission'):
            self.invoke()

    def test_kit_view_id_rotation_is_not_semantic_change(self):
        self.after = copy.deepcopy(self.rows)
        self.after[0]['id'] = 'rotated-kit-view'
        self.assertIsNone(self.invoke())

    def test_nonboolean_effective_allowed_field_rejected(self):
        for value in (0, 1, 'false'):
            with self.subTest(value=value):
                self.allowed_override = value
                with self.assertRaises(ValueError):
                    self.invoke()

    def test_effective_policy_mismatch_rejected_even_with_valid_rules(self):
        self.allowed_override = True
        with self.assertRaises(ValueError):
            self.invoke()

    def test_shared_deadline_expiry_prevents_query(self):
        with patch.object(policy.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaises(TimeoutError):
                self.invoke(timeout=1)
        self.runtime.transport.control.assert_not_called()

    def test_transport_error_is_not_retried(self):
        self.runtime.transport.control.side_effect = TimeoutError('synthetic timeout')
        with self.assertRaises(TimeoutError):
            self.invoke()
        self.runtime.transport.control.assert_called_once()

    def test_invalid_query_returncode_is_not_treated_as_denial(self):
        self.returncode = 2
        with self.assertRaises(RuntimeError):
            self.invoke()

    def test_invalid_timeout_or_stage_rejected_before_transport(self):
        for timeout in (0, -1, True, float('inf'), float('nan')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.invoke(timeout=timeout)
        with self.assertRaises(ValueError):
            self.invoke('unknown')
        self.runtime.transport.control.assert_not_called()

    def test_catalog_access_still_rejects_production_without_exact_trial_checker(self):
        self.runtime.registration['production_enabled'] = True
        with self.assertRaisesRegex(ValueError, 'Catalog-only'):
            policy.check_network(self.runtime, 'machine', stage='before_model', repo=None,
                                 timeout=30, catalog_access=True)
        self.runtime.transport.control.assert_not_called()


if __name__ == '__main__':
    unittest.main()

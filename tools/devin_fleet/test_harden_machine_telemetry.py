"""Synthetic deny-only maintenance transport; no VM or real network."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import harden_machine_telemetry as harden
from test_model_network_admission import rules


class HardenTests(unittest.TestCase):
    def setUp(self):
        self.rows=rules()
        self.events=[]
        self.fail=False
        self.runtime=SimpleNamespace(_entered=True,_failed=False,_active={},
            registration={'production_enabled':False,'roles':{'machine':{'id':harden.MACHINE,'name':'e-base-machine'}}},
            transport=SimpleNamespace(control=Mock(side_effect=self.query)))
        for name in ('require_managed_namespace','global_lock_held','inventory','check_network'):
            ctx=patch.object(harden,name,return_value=True);ctx.start();self.addCleanup(ctx.stop)
    def query(self,argv,timeout):
        self.assertEqual(argv[:2],['/usr/bin/sbx','policy'])
        self.assertEqual(timeout,10)
        self.events.append(argv[2])
        if argv[2]=='ls': return SimpleNamespace(returncode=0,stdout=json.dumps({'rules':self.rows}))
        self.assertEqual(argv,['/usr/bin/sbx','policy','deny','network','--sandbox','e-base-machine',','.join(sorted(harden.DENY_ONLY_HOSTS))])
        self.rows.append(dict(self.rows[1],id='telemetry',resources=sorted(harden.DENY_ONLY_HOSTS)))
        if self.fail: raise TimeoutError('uncertain add')
        return SimpleNamespace(returncode=0,stdout='')
    def invoke(self):
        return harden.apply_closed(self.runtime,before_add=lambda:self.events.append('journal'))
    def test_add_preserves_blanket_and_journals_before_only_mutation(self):
        before=copy.deepcopy(self.rows)
        result=self.invoke()
        self.assertTrue(result['deny_added']);self.assertTrue(result['network_denied'])
        self.assertEqual(self.rows[:2],before)
        self.assertEqual(self.events,['ls','journal','deny','ls'])
    def test_existing_deny_causes_no_mutation(self):
        self.rows.append(dict(self.rows[1],id='telemetry',resources=sorted(harden.DENY_ONLY_HOSTS)))
        self.assertFalse(self.invoke()['deny_added']);self.assertEqual(self.events,['ls','ls'])
    def test_uncertain_mutation_is_not_retried(self):
        self.fail=True
        with self.assertRaises(TimeoutError): self.invoke()
        self.assertEqual(self.events,['ls','journal','deny'])
    def test_other_scope_cannot_satisfy_deny(self):
        self.rows.append(dict(self.rows[1],id='telemetry',scope='sandbox:e-base-stdlib',resources=sorted(harden.DENY_ONLY_HOSTS)))
        with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(self.events,['ls'])
    def test_active_vm_refused(self):
        self.runtime._active={'machine':object()}
        with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(self.events,[])


if __name__=='__main__':unittest.main()

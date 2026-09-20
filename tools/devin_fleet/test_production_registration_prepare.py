import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import production_registration_prepare as prep
import production_registration_candidate as candidate

class PrepareTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/tmp');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.run=self.root/'production-registration-preparation-v1'
        for target,name,value in ((prep,'ROOT',self.root),(prep,'RUN',self.run),(candidate,'ROOT',self.root)):
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        for name,value in (('require_managed_namespace',None),('global_lock_held',True)):
            p=patch.object(prep,name,return_value=value);p.start();self.addCleanup(p.stop)
        roles={r:{'id':str(uuid.uuid5(uuid.NAMESPACE_DNS,r)),'name':'e-base-'+r} for r in candidate.ROLES}
        value={'schema':1,'distro':'EBase-Sandboxes','user':'fleet','resources_per_sandbox':{'cpus':2,'memory':'4g'},'roles':roles,'simultaneous_capacity_verified':1,'production_enabled':False}
        (self.root/'sandbox-registry.json').write_text(json.dumps(value));(self.root/'sandbox-registry.json').chmod(0o600)

    def test_prepare_and_independent_inspect(self):
        result=prep.prepare();self.assertTrue(result['prepared']);self.assertFalse(result['activated'])
        self.assertEqual(result,prep.inspect())
        self.assertFalse(json.loads((self.root/'sandbox-registry.json').read_text())['production_enabled'])
        with self.assertRaises(FileExistsError):prep.prepare()

    def test_partial_or_changed_state_refused(self):
        result=prep.prepare();production=Path(result['controller_root'])
        (production/'cycles'/'unexpected').touch()
        with self.assertRaises(ValueError):prep.inspect()

    def test_missing_commit_is_never_resumed(self):
        self.run.mkdir(mode=0o700)
        (self.run/'status.json').write_text('{}')
        with self.assertRaises(ValueError):prep.inspect()
        with self.assertRaises(FileExistsError):prep.prepare()

    def test_lock_required_before_reservation(self):
        with patch.object(prep,'global_lock_held',return_value=False):
            with self.assertRaises(ValueError):prep.prepare()
        self.assertFalse(self.run.exists())

if __name__=='__main__':unittest.main()

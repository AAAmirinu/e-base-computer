import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import registered_turn_input as loader


class InputTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/tmp');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        p=patch.object(loader,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.identity='a'*32
        self.directory=self.root/'turn-inputs'/self.identity
        self.directory.mkdir(parents=True,mode=0o700)
        self.directory.parent.chmod(0o700)
        self.production=self.root/('production-'+'b'*32);self.production.mkdir(mode=0o700)
        for name in ('project','cycles'):(self.production/name).mkdir(mode=0o700)
        self.registry={'production_enabled':True,'controller_root':str(self.production),'roles':{'machine':{}}}
        self.request=dict(schema=1,role='machine',project_root=str(self.production/'project'),sequence=0,
            entry={},state={},settings={},parent_ref='refs/heads/main',parent_bundle_sha256=hashlib.sha256(b'bundle').hexdigest())
        self.write(self.root/'sandbox-registry.json',self.registry)
        self.write(self.directory/'request.json',self.request)
        (self.directory/'parent.bundle').write_bytes(b'bundle')

    def write(self,path,value):
        path.write_text(json.dumps(value));path.chmod(0o600)

    def test_reads_without_reserving(self):
        result=loader.load(self.identity)
        self.assertEqual(result['parent_bundle'],b'bundle')
        self.assertEqual(result['cycle_directory'],self.production/'cycles'/self.identity)
        self.assertFalse(result['cycle_directory'].exists())

    def test_malformed_requests(self):
        for change in ({'sequence':True},{'extra':1},{'parent_ref':'refs/heads/../main'},
                       {'project_root':'/tmp'},{'parent_bundle_sha256':'0'*64},{'settings':[]}):
            self.write(self.directory/'request.json',dict(self.request,**change))
            with self.assertRaises(ValueError):loader.load(self.identity)

    def test_stop_and_consumed_cycle(self):
        (self.production/'STOP').touch()
        with self.assertRaises(ValueError):loader.load(self.identity)
        (self.production/'STOP').unlink()
        (self.production/'cycles'/self.identity).mkdir()
        with self.assertRaises(ValueError):loader.load(self.identity)

    def test_duplicate_nonfinite_and_link(self):
        path=self.directory/'request.json'
        for raw in ('{"schema":1,"schema":1}', '{"value":NaN}'):
            path.write_text(raw)
            with self.assertRaises(ValueError):loader.load(self.identity)
        path.unlink();path.symlink_to(self.root/'sandbox-registry.json')
        with self.assertRaises(ValueError):loader.load(self.identity)

    def test_registration_and_identity_rejected(self):
        self.registry['production_enabled']=False
        self.write(self.root/'sandbox-registry.json',self.registry)
        for identity in (self.identity,'../escape',None):
            with self.assertRaises(ValueError):loader.load(identity)


if __name__=='__main__':unittest.main()

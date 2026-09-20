import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import observed_boundary_admission as probe
from sandbox_repository import GuestRepository
from sandbox_runtime import SandboxRuntime


class ObservedBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.runtime=object.__new__(SandboxRuntime)
        self.runtime._entered=True
        self.runtime._failed=False
        self.runtime.stop_path=self.root/'STOP'
        self.runtime.registration={'roles':{'machine':{'id':'fixed-id'}}}
        self.controller=Mock(fenced=False,sandbox_id='fixed-id')
        self.repo=GuestRepository(self.controller,'/home/agent/workspace/machine',self.root/'logs',
                                  external_stop=self.runtime.stop_path)
        self.runtime._active={'machine':(None,self.controller)}
        self.calls=[]
        self.host=self.patch('check_host_boundary',side_effect=lambda *a,**k:self.calls.append('host'))
        self.validator=self.patch('validate_guest_contract',side_effect=lambda v:self.calls.append('validate'))
        self.patch('require_managed_namespace')
        self.patch('_file',side_effect=self.read)
        self.controller.execute.side_effect=self.execute
        self.callback=probe.make_boundary_check('sha256:'+'a'*64)
        self.raw=None

    def patch(self,name,**kwargs):
        context=patch.object(probe,name,**kwargs)
        value=context.start()
        self.addCleanup(context.stop)
        return value

    def read(self,path,limit):
        return b'# trusted fixture' if path.name=='guest_boundary_metadata.py' else self.raw

    def execute(self,argv,**kwargs):
        self.calls.append('guest')
        self.assertEqual(argv[:3],['/usr/bin/python3','-I','-c'])
        self.assertEqual(kwargs['cwd'],'/')
        self.assertEqual(kwargs['external_stop'],self.runtime.stop_path)
        self.raw=(argv[-1]+json.dumps({'synthetic':True})+'\n').encode()
        return SimpleNamespace(returncode=0)

    def invoke(self,stage='before_prepare',repo=None):
        return self.callback(self.runtime,'machine',stage=stage,
                             repo=(None if stage=='initial' else self.repo) if repo is None else repo,timeout=90)

    def test_order_and_same_lease(self):
        self.assertIsNone(self.invoke())
        self.assertEqual(self.calls,['host','guest','validate','host'])
        self.controller.stop.assert_not_called()

    def test_initial_never_starts_guest(self):
        self.invoke('initial')
        self.assertEqual(self.calls,['host'])
        self.controller.execute.assert_not_called()

    def test_failed_guest_stops_and_poison_runtime(self):
        self.validator.side_effect=ValueError('unsafe')
        with self.assertRaises(ValueError): self.invoke()
        self.assertTrue(self.runtime._failed)
        self.controller.stop.assert_called_once()
        with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(self.controller.execute.call_count,1)

    def test_host_change_after_guest_stops(self):
        self.host.side_effect=[None,ValueError('changed')]
        with self.assertRaises(ValueError): self.invoke()
        self.controller.stop.assert_called_once()

    def test_initial_host_failure_poison_runtime(self):
        self.host.side_effect=ValueError('unsafe')
        with self.assertRaises(ValueError): self.invoke('initial')
        self.assertTrue(self.runtime._failed)
        self.controller.execute.assert_not_called()

    def test_unowned_lease_rejected(self):
        other=GuestRepository(Mock(),'/home/agent/workspace/machine',self.root/'other')
        with self.assertRaises(ValueError): self.invoke(repo=other)
        self.host.assert_not_called()

    def test_stop_before_guest(self):
        self.runtime.stop_path.touch()
        with self.assertRaises(RuntimeError): self.invoke()
        self.controller.execute.assert_not_called()
        self.controller.stop.assert_called_once()


if __name__=='__main__': unittest.main()

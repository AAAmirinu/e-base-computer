from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import registered_turn_guards as guards


class RegisteredGuardsTests(unittest.TestCase):
    def setUp(self):
        self.registration={'production_enabled':True,'roles':{'machine':{
            'name':'e-base-machine','image_digest':'sha256:'+'a'*64}}}
        self.events=[]
        self.boundary=self.mock('make_boundary_check',return_value=Mock())
        self.admission=self.mock('make_admission',return_value=Mock())
        self.host=self.mock('check_host_boundary',side_effect=lambda *a,**k:self.events.append('host'))
        self.window=self.mock('model_network_window',side_effect=self.scope)

    def mock(self,name,**kwargs):
        context=patch.object(guards,name,**kwargs)
        value=context.start()
        self.addCleanup(context.stop)
        return value

    @contextmanager
    def scope(self,*args,**kwargs):
        self.events.append('open')
        try: yield
        finally: self.events.append('close')

    def make(self):
        return guards.make_registered_turn_guards(self.registration,'machine',{'paths':['src/**']},{})

    def test_constructs_live_dependencies_without_execution(self):
        result=self.make()
        self.assertIs(result['admission'],self.admission.return_value)
        self.assertIs(self.admission.call_args.kwargs['boundary_check'],self.boundary.return_value)
        self.assertIs(self.admission.call_args.kwargs['network_check'],guards.check_network)
        self.host.assert_not_called()
        self.window.assert_not_called()

    def test_disabled_or_unpinned_refused(self):
        for change in ('disabled','missing','tag'):
            with self.subTest(change=change):
                original=deepcopy(self.registration)
                if change=='disabled': self.registration['production_enabled']=False
                elif change=='missing': self.registration['roles']['machine'].pop('image_digest')
                else: self.registration['roles']['machine']['image_digest']='latest'
                with self.assertRaises(ValueError): self.make()
                self.registration=original
        self.admission.assert_not_called()

    def test_host_before_open_and_close_after_exception(self):
        result=self.make()
        runtime=SimpleNamespace(registration=deepcopy(self.registration))
        with self.assertRaises(RuntimeError):
            with result['network_scope'](runtime,'machine',object(),'/fixed',timeout=20):
                self.events.append('body')
                raise RuntimeError('test')
        self.assertEqual(self.events,['host','open','body','close'])

    def test_host_rejection_never_opens(self):
        result=self.make()
        self.host.side_effect=ValueError('unsafe')
        with self.assertRaises(ValueError):
            with result['network_scope'](SimpleNamespace(registration=self.registration),'machine',None,None,timeout=20): pass
        self.window.assert_not_called()

    def test_registration_is_frozen(self):
        result=self.make()
        self.registration['roles']['machine']['image_digest']='sha256:'+'b'*64
        with self.assertRaises(ValueError):
            with result['network_scope'](SimpleNamespace(registration=self.registration),'machine',None,None,timeout=20): pass
        self.host.assert_not_called()

    def test_different_role_refused(self):
        result=self.make()
        with self.assertRaises(ValueError):
            with result['network_scope'](SimpleNamespace(registration=self.registration),'kernel',None,None,timeout=20): pass
        self.window.assert_not_called()

    def test_pipeline_entry_supplies_both_fixed_guards(self):
        import sandbox_one_turn
        fixed=self.make()
        args=dict(registration=self.registration,controller_root='/root',project_root='/project',
                  role='machine',entry={},state={},settings={},cycle_directory='/root/cycle',
                  sequence=0,runtime_factory=Mock(),validate=Mock(),build_and_import=Mock())
        with patch.object(guards,'make_registered_turn_guards',return_value=fixed) as factory, \
             patch.object(sandbox_one_turn,'run_one_turn',return_value='synthetic-result') as pipeline:
            self.assertEqual(sandbox_one_turn.run_registered_one_turn(**args),'synthetic-result')
        factory.assert_called_once_with(self.registration,'machine',{}, {})
        self.assertIs(pipeline.call_args.kwargs['admission'],fixed['admission'])
        self.assertIs(pipeline.call_args.kwargs['network_scope'],fixed['network_scope'])

    def test_pipeline_rejects_unregistered_before_stages(self):
        import sandbox_one_turn
        self.registration['production_enabled']=False
        with patch.object(sandbox_one_turn,'run_one_turn') as pipeline:
            with self.assertRaises(ValueError):
                sandbox_one_turn.run_registered_one_turn(registration=self.registration,
                    controller_root='/root',project_root='/project',role='machine',entry={},
                    state={},settings={},cycle_directory='/root/cycle',sequence=0,
                    runtime_factory=Mock(),validate=Mock(),build_and_import=Mock())
            pipeline.assert_not_called()


if __name__=='__main__': unittest.main()

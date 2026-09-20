import unittest
from pathlib import Path
import subprocess
import sys
from guest_mcp_inspect import ORDER, validate
from guest_mcp_prepare import MODULES


class GuestInspectTests(unittest.TestCase):
    def test_discovery_profile_in_fresh_interpreter(self):
        script=r'''
import base64,hashlib,json,shutil,sys,tempfile,zlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import guest_mcp_prepare as prep
import guest_mcp_inspect as inspect
sources=prep.decode_sources(prep.encode_sources(sys.argv[1]))
sources['mcp_override_probe.py'] += '\ndef read_global(name):\n    return b\'{"mcpServers":{"synthetic":{"url":"https://invalid.example"}}}\'\n'
payload={k:dict(source=v,sha256=hashlib.sha256(v.encode()).hexdigest()) for k,v in sources.items()}
encoded=base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
profile=sys.argv[3]
compatible=profile=='compatible_control'
params=profile=='params_control'
if compatible or params:profile='echo_control'
source=(Path(sys.argv[1])/('mcp_'+profile+'_inputs.py')).read_text()
if compatible:
    from mcp_compatible_control_source import compose
    source=compose(source,(Path(sys.argv[1])/'mcp_fixture_compat.py').read_text())
if params:
    from mcp_params_control_source import compose
    source=compose(source,(Path(sys.argv[1])/'mcp_fixture_compat.py').read_text(),
                   (Path(sys.argv[1])/'mcp_fixture_params.py').read_text())
with tempfile.TemporaryDirectory(dir='/tmp') as root:
    state=Path(root)/'discovery'
    attribute={'discovery':'DISCOVERY_STATE','wildcard_denial':'WILDCARD_STATE','echo_control':'CONTROL_STATE'}[profile]
    if compatible:attribute='COMPATIBLE_CONTROL_STATE'
    if params:attribute='PARAMS_CONTROL_STATE'
    setattr(prep,attribute,str(state));setattr(inspect,attribute,str(state))
    work=None
    try:
        mode=sys.argv[2]
        if mode=='old':
            # Deliberately create old-profile data under a temporary path.
            setattr(prep,attribute,str(Path(root)/'other'))
            prep.prepare(encoded,state_directory=state)
        else: prep.prepare(encoded,state_directory=state,discovery_source=source)
        work=Path(json.loads((state/'mcp-denial-v1'/'attempt.json').read_bytes())['work'])
        if mode=='input':(work/'prompt.txt').write_bytes(b'changed')
        if mode=='hold':(state/'prepare-only').unlink()
        if mode=='launch':(state/'mcp-denial-v1'/'launch.json').write_bytes(b'{}')
        if mode=='reentry':
            for name in inspect.ORDER:sys.modules.pop(name,None)
            try:prep.prepare(encoded,state_directory=state,discovery_source=source)
            except FileExistsError:pass
            else:raise AssertionError('Consumed preparation was overwritten')
        for name in inspect.ORDER:sys.modules.pop(name,None)
        check={'discovery':inspect.inspect_discovery,'wildcard_denial':inspect.inspect_wildcard,'echo_control':inspect.inspect_control}[profile]
        if compatible:check=inspect.inspect_compatible_control
        if params:check=inspect.inspect_params_control
        try: result=check(encoded,source)
        except (ValueError,OSError):
            if mode in ('valid','reentry'):raise
        else:
            assert mode in ('valid','reentry')
            assert result['prepared_state_verified'] and not result['model_executed']
    finally:
        if work is not None:
            assert work.parent==Path('/tmp') and work.name.startswith('e-base-mcp-probe-')
            shutil.rmtree(work)
'''
        for profile in ('discovery','wildcard_denial','echo_control','compatible_control','params_control'):
            for mode in ('valid','old','input','hold','launch','reentry'):
                with self.subTest(profile=profile,mode=mode):
                    result=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).parent),mode,profile],capture_output=True,timeout=15)
                    self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_real_preparation_and_inspection_in_fresh_processes(self):
        # Trusted synthetic controller fixture only: no guest, CLI, credentials or network.
        script = r'''
import base64,hashlib,json,os,shutil,sys,tempfile,zlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from guest_mcp_prepare import encode_sources,decode_sources,prepare
from guest_mcp_inspect import inspect_prepared,ORDER
sources=decode_sources(encode_sources(sys.argv[1]))
sources['mcp_override_probe.py'] += '\ndef read_global(name):\n    return b\'{"mcpServers":{"synthetic":{"url":"https://invalid.example"}}}\'\n'
payload={name:dict(source=value,sha256=hashlib.sha256(value.encode()).hexdigest()) for name,value in sources.items()}
encoded=base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
with tempfile.TemporaryDirectory(prefix='mcp-inspect-test-',dir='/tmp') as root:
    state=Path(root)/'state'
    work=None
    try:
        prepare(encoded,state_directory=state)
        work=Path(json.loads((state/'mcp-denial-v1'/'attempt.json').read_bytes())['work'])
        mode=sys.argv[2]
        if mode=='input': (work/'prompt.txt').write_bytes(b'changed')
        if mode=='launch': (state/'mcp-denial-v1'/'launch.json').symlink_to(state/'missing')
        if mode=='hold': (state/'prepare-only').unlink()
        if mode=='source': (state/'sources'/'mcp_probe_audit.py').write_bytes(b'raise RuntimeError("must not execute")')
        if mode=='cache':
            cache=state/'sources'/'__pycache__'
            cache.mkdir(exist_ok=True)
            cache.chmod(0o777)
        for name in ORDER: sys.modules.pop(name,None)
        try:
            result=inspect_prepared(encoded,state_directory=state)
        except (ValueError,OSError):
            if mode=='valid': raise
        else:
            assert mode=='valid', 'unsafe state accepted'
            assert result['prepared_state_verified'] and not result['model_executed']
    finally:
        if work is not None:
            assert work.parent==Path('/tmp') and work.name.startswith('e-base-mcp-probe-')
            shutil.rmtree(work)
'''
        for mode in ('valid','input','launch','hold','source','cache'):
            with self.subTest(mode=mode):
                result=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).parent),mode],
                                      capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_dependency_set(self):
        self.assertEqual({name+'.py' for name in ORDER},set(MODULES))
        self.assertEqual(len(ORDER),len(set(ORDER)))

    def test_receipt_is_not_model_acceptance(self):
        value=dict(prepared_state_verified=True,prepare_only_retained=True,launch_absent=True,
                   input_count=9,model_executed=False,production_admitted=False)
        self.assertEqual(validate(value),value)
        for key,new in [('model_executed',True),('production_admitted',True),
                        ('input_count',True),('launch_absent',False),('prepare_only_retained',False)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate(dict(value,**{key:new}))

    def test_failed_receipt(self):
        validate(dict(prepared_state_verified=False,prepare_only_retained=False,launch_absent=False,
                      input_count=0,model_executed=False,production_admitted=False))


if __name__=='__main__': unittest.main()

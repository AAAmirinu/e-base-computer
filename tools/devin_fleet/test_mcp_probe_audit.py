import io
import os
from pathlib import Path
import tempfile
import unittest
from mcp_denial_fixture import serve
from mcp_probe_audit import (open_audit, record_event, summarize_audit,
                             record_nonce_event, summarize_nonce_audit)
from mcp_denial_evidence import summarize_with_audit
from test_mcp_denial_probe import export


class AuditTests(unittest.TestCase):
    def test_called_or_reinitialized_audit_disqualifies_denial(self):
        baseline=b'initialized\nlisted\n'
        value=summarize_with_audit(export(),baseline)
        self.assertTrue(value['permission_denial_observed'])
        self.assertFalse(value['passed'])
        self.assertFalse(value['cli_session_bound'])
        for suffix in (b'called\n', b'initialized\n'):
            self.assertFalse(summarize_with_audit(export(),baseline+suffix)['permission_denial_observed'])

    def test_malformed_tool_request_is_still_logged(self):
        events=[]
        with self.assertRaises(ValueError):
            serve(io.StringIO('{"jsonrpc":"2.0","id":null,"method":"tools/call"}\n'),
                  io.StringIO(),events.append)
        self.assertEqual(events,['called'])

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='e-base-mcp-probe-',dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.root.chmod(0o700)
        self.path=self.root/'fixture-events.log'
        fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        os.close(fd)

    def test_fixed_events_and_discovery(self):
        fd=open_audit(str(self.path))
        self.addCleanup(os.close,fd)
        source=io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
                          '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')
        serve(source,io.StringIO(),lambda event:record_event(fd,event))
        result=summarize_audit(self.path.read_bytes())
        self.assertTrue(result['discovery_sequence_observed'])
        self.assertFalse(result['cli_session_bound'])
        self.assertEqual(result['tool_call_count'],0)

    def test_invocation_logs_no_arguments(self):
        events=[]
        serve(io.StringIO('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"secret":"PRIVATE"}}\n'),
              io.StringIO(),events.append)
        self.assertEqual(events,['called'])

    def test_bad_path_mode_and_symlink_refused(self):
        with self.assertRaises(ValueError): open_audit('/tmp/elsewhere/fixture-events.log')
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): open_audit(str(self.path))
        self.path.unlink()
        self.path.symlink_to(self.root/'missing')
        with self.assertRaises(OSError): open_audit(str(self.path))

    def test_hardlink_refused(self):
        os.link(self.path,self.root/'alias')
        with self.assertRaises(ValueError): open_audit(str(self.path))

    def test_reserved_inode_and_nonce_events(self):
        info=self.path.stat()
        identity=(info.st_dev,info.st_ino)
        with self.assertRaises(ValueError):
            open_audit(str(self.path),expected_identity=(info.st_dev,info.st_ino+1))
        fd=open_audit(str(self.path),expected_identity=identity)
        self.addCleanup(os.close,fd)
        nonce='a'*32
        record_nonce_event(fd,nonce,'initialized')
        record_nonce_event(fd,nonce,'listed')
        result=summarize_nonce_audit(self.path.read_bytes(),nonce)
        self.assertTrue(result['attempt_nonce_verified'])
        self.assertTrue(result['discovery_sequence_observed'])
        self.assertFalse(result['cli_session_bound'])

    def test_nonce_parser_rejects_mixing_partial_and_overflow(self):
        nonce='a'*32
        event=(nonce+':listed\n').encode()
        for raw in (b'',event[:-1],event*65,('b'*32+':listed\n').encode(),
                    (nonce+':unknown\n').encode()):
            with self.assertRaises(ValueError): summarize_nonce_audit(raw,nonce)
        fd=open_audit(str(self.path))
        self.addCleanup(os.close,fd)
        with self.assertRaises(ValueError): record_nonce_event(fd,'bad','listed')
        with self.assertRaises(ValueError): record_nonce_event(fd,nonce,'PRIVATE')
        self.assertEqual(self.path.read_bytes(),b'')

    def test_events_and_bounds_fail_closed(self):
        for raw in (b'listed\ninitialized\n', b''):
            self.assertFalse(summarize_audit(raw)['discovery_sequence_observed'])
        for raw in (b'private\n',b'listed',b'x'*1025):
            with self.assertRaises(ValueError): summarize_audit(raw)
        fd=open_audit(str(self.path))
        self.addCleanup(os.close,fd)
        with self.assertRaises(ValueError): record_event(fd,'PRIVATE')


if __name__=='__main__': unittest.main()

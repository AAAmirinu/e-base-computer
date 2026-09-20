import hashlib
from pathlib import Path
import tempfile
import unittest
from mcp_cli_identity import _verify,_verify_install


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir='/tmp'); self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'cli'; self.path.write_bytes(b'synthetic executable'); self.path.chmod(0o700)
        self.pin=hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_exact_bytes(self): self.assertEqual(_verify(self.path,self.pin),self.pin)

    def test_changed_bytes(self):
        self.path.write_bytes(b'changed')
        with self.assertRaises(ValueError): _verify(self.path,self.pin)

    def test_writable_or_nonexecutable_refused(self):
        for mode in (0o777,0o600):
            self.path.chmod(mode)
            with self.assertRaises(ValueError): _verify(self.path,self.pin)

    def test_symlink_refused(self):
        link=self.path.parent/'link'; link.symlink_to(self.path)
        with self.assertRaises(OSError): _verify(link,self.pin)

    def installation(self):
        root=self.path.parent
        storage=root/'versions'; storage.mkdir(mode=0o700)
        version=storage/'version'; version.mkdir(mode=0o700)
        binary=version/'devin'; binary.write_bytes(self.path.read_bytes()); binary.chmod(0o700)
        current=storage/'current'; current.symlink_to(version,target_is_directory=True)
        target=str(current/'devin')
        link=root/'entry'; link.symlink_to(target)
        return link,target,storage,binary

    def test_exact_link_and_pinned_version(self):
        link,target,storage,binary=self.installation()
        self.assertEqual(_verify_install(link,target,storage,self.pin),self.pin)
        binary.write_bytes(b'changed version')
        with self.assertRaises(ValueError): _verify_install(link,target,storage,self.pin)

    def test_storage_escape_and_unknown_link_refused(self):
        link,target,storage,binary=self.installation()
        link.unlink(); link.symlink_to(self.path)
        with self.assertRaises(ValueError): _verify_install(link,target,storage,self.pin)
        with self.assertRaises(ValueError): _verify_install(link,str(self.path),storage,self.pin)

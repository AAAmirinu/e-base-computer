"""Pure candidate-builder admission tests; no Git or repository code runs."""
import unittest
import hashlib
from unittest.mock import patch

import container_candidate_commit as builder
from test_snapshot_git_tree import snapshot


CONFIG = (b'core.repositoryformatversion\n0\0core.filemode\ntrue\0'
          b'core.bare\nfalse\0core.logallrefupdates\ntrue\0')


class AdmissionTests(unittest.TestCase):
    def test_parent_branch_contract_before_any_write(self):
        args = snapshot([('x', '100644', b'x')])
        bundle = b'inert bundle'
        sha = hashlib.sha256(bundle).hexdigest()
        with patch.object(builder.os, 'getuid', return_value=65532), \
                patch.object(builder.Path, 'is_file', return_value=True), \
                patch.dict(builder.os.environ, {'HOME': '/work'}, clear=True), \
                patch.object(builder.Path, 'open', side_effect=RuntimeError('write boundary')) as opened, \
                patch.object(builder.subprocess, 'run') as run:
            for ref in ('refs/heads/fleet/integration', 'refs/heads/machine-next'):
                with self.subTest(ref=ref), self.assertRaisesRegex(RuntimeError, 'write boundary'):
                    builder.build_candidate(*args, bundle, sha, ref)
            opened.reset_mock()
            for ref in ('--upload-pack=bad', 'refs/tags/main', 'refs/heads/../main',
                        'refs/heads/main.lock', 'refs/heads/a b', None):
                with self.subTest(ref=ref), self.assertRaises(ValueError):
                    builder.build_candidate(*args, bundle, sha, ref)
            opened.assert_not_called()
            run.assert_not_called()

    def test_expected_config(self):
        builder.verify_fresh_config(CONFIG)

    def test_unsafe_template_configs_rejected(self):
        for key in (b'core.hooksPath', b'core.fsmonitor', b'filter.bad.clean',
                    b'include.path', b'credential.helper', b'core.sshCommand',
                    b'commit.gpgsign', b'gpg.program'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                builder.verify_fresh_config(CONFIG + key + b'\nanything\0')

    def test_duplicate_missing_and_changed_values_rejected(self):
        for value in (b'', CONFIG[:-1], CONFIG + b'core.bare\nfalse\0',
                      CONFIG.replace(b'core.filemode\ntrue\0', b''),
                      CONFIG.replace(b'\nfalse', b'\ntrue')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                builder.verify_fresh_config(value)

    def test_outer_uid_rejected_before_git_or_files(self):
        with patch.object(builder.os, 'getuid', return_value=1000), \
                patch.object(builder.subprocess, 'run', side_effect=AssertionError('Git forbidden')) as run, \
                patch.object(builder, 'materialize_snapshot', side_effect=AssertionError('Writes forbidden')) as materialize:
            with self.assertRaises(RuntimeError):
                builder.build_candidate(b'', '', {}, b'', '', '')
            run.assert_not_called()
            materialize.assert_not_called()

    def test_import_outer_uid_rejected_before_git(self):
        with patch.object(builder.os, 'getuid', return_value=1000), \
                patch.object(builder.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                builder.verify_import(b'', '', {}, b'', {})
            run.assert_not_called()

    def test_import_mismatched_metadata_rejected_before_writes(self):
        raw, digest, blobs = snapshot([('x', '100644', b'x')])
        expected = builder.expected_tree(raw, digest, blobs)
        bundle = b'inert test bundle'
        metadata = dict(tree=expected['tree'], parent=expected['base'], manifest_sha256=digest,
                        commit='b'*40, bundle_bytes=len(bundle), bundle_sha256=hashlib.sha256(bundle).hexdigest())
        with patch.object(builder.os, 'getuid', return_value=65532), \
                patch.object(builder.Path, 'is_file', return_value=True), \
                patch.dict(builder.os.environ, {'HOME':'/work'}, clear=True), \
                patch.object(builder.Path, 'mkdir', side_effect=AssertionError('Writes forbidden')), \
                patch.object(builder.subprocess, 'run', side_effect=AssertionError('Git forbidden')):
            for key, wrong in [('tree', '0'*40), ('parent', '0'*40), ('manifest_sha256', '0'*64),
                               ('bundle_bytes', 0), ('bundle_sha256', '0'*64), ('commit', '../bad')]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    builder.verify_import(raw, digest, blobs, bundle, dict(metadata, **{key:wrong}))


if __name__ == '__main__':
    unittest.main()

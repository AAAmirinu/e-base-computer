"""Pure trusted policy tests; no Git, guest source, or subprocess execution."""
import unittest

from guest_git_read_policy import SOURCE


class GuestGitReadPolicyTests(unittest.TestCase):
    def setUp(self):
        namespace = {}
        exec(SOURCE, namespace)
        self.arguments = namespace['read_git_args']
        self.config = namespace['check_read_git_config']
        self.core = (b'core.repositoryformatversion\n0\0core.filemode\ntrue\0'
                     b'core.bare\nfalse\0core.logallrefupdates\ntrue\0')

    def test_four_exact_read_commands_and_diff_safety_flags(self):
        for command in (['rev-parse', 'HEAD'], ['ls-files', '-z'],
                        ['ls-files', '--others', '--exclude-standard', '-z']):
            self.assertEqual(self.arguments(command), command)
        self.assertEqual(self.arguments(['diff', '--no-renames', '--name-only', '-z', 'HEAD']),
                         ['diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=all',
                          '--no-renames', '--name-only', '-z', 'HEAD'])

    def test_additional_commands_flags_or_revisions_rejected(self):
        for command in ([], ['status'], ['config', '--list'], ['rev-parse', 'main'],
                        ['rev-parse', 'HEAD', '--'], ['ls-files'], ['add', '--all'],
                        ['commit', '-m', 'x'], ['-c', 'alias.x=!bad', 'x'],
                        ['diff', '--no-renames', '--name-only', '-z', 'HEAD', '--ext-diff']):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.arguments(command)

    def test_allowed_argument_input_is_not_mutated_or_returned_by_reference(self):
        original = ['ls-files', '-z']
        returned = self.arguments(original)
        returned.append('extra')
        self.assertEqual(original, ['ls-files', '-z'])

    def test_fresh_core_and_data_only_fields_accepted(self):
        self.config(self.core)
        self.config(self.core + b'user.name\nSynthetic User\0user.email\nsynthetic@example.invalid\0'
                    b'remote.origin.url\nhttps://example.invalid/repo\0'
                    b'remote.origin.fetch\n+refs/heads/*:refs/remotes/origin/*\0'
                    b'remote.origin.pushurl\nhttps://example.invalid/other\0')

    def test_include_filter_fsmonitor_signature_and_unknown_settings_rejected(self):
        for name in (b'include.path', b'includeif.gitdir:foo.path', b'filter.foo.clean',
                     b'filter.foo.process', b'core.fsmonitor', b'core.hookspath',
                     b'commit.gpgsign', b'gpg.program', b'core.sshcommand', b'alias.test',
                     b'diff.external', b'diff.foo.textconv', b'credential.helper',
                     b'extensions.partialclone', b'remote.origin.promisor', b'unknown.setting'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.config(self.core + name + b'\nvalue\0')

    def test_duplicate_even_identical_values_rejected(self):
        for extra in (b'core.filemode\ntrue\0', b'user.name\nx\0user.name\nx\0'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.config(self.core + extra)

    def test_core_values_are_fixed_and_all_required(self):
        for old, new in ((b'repositoryformatversion\n0', b'repositoryformatversion\n1'),
                         (b'filemode\ntrue', b'filemode\nfalse'),
                         (b'bare\nfalse', b'bare\ntrue'),
                         (b'logallrefupdates\ntrue', b'logallrefupdates\nfalse')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.config(self.core.replace(old, new))
        with self.assertRaises(ValueError):
            self.config(self.core.replace(b'core.filemode\ntrue\0', b''))

    def test_malformed_or_unbounded_configuration_rejected(self):
        for raw in (b'', self.core[:-1], self.core.decode(), b'x' * 65537,
                    self.core + b'user.name\0', self.core + b'user.name\nx\ny\0',
                    self.core + b'user.name\nx\ry\0',
                    self.core + b'user.name\n' + b'x' * 4097 + b'\0'):
            with self.subTest(kind=type(raw).__name__, size=len(raw)), self.assertRaises(ValueError):
                self.config(raw)


if __name__ == '__main__':
    unittest.main()

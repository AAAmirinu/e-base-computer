"""Pure Debian source conversion tests; no APT or subprocess execution."""
import unittest
from unittest.mock import patch

import install_validation_git as installer


def sources(scheme='http'):
    return ('Types: deb\nURIs: ' + scheme + '://deb.debian.org/debian\n'
            'Suites: trixie trixie-updates\nComponents: main\nSigned-By: ' + installer.KEYRING +
            '\n\nTypes: deb\nURIs: ' + scheme + '://deb.debian.org/debian-security\n'
            'Suites: trixie-security\nComponents: main\nSigned-By: ' + installer.KEYRING + '\n')


class HttpsSourcesTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(installer.subprocess, 'run', side_effect=AssertionError('Subprocess forbidden'))
        self.run = guard.start()
        self.addCleanup(guard.stop)
        self.addCleanup(self.run.assert_not_called)

    def reject(self, raw):
        with self.assertRaises(ValueError):
            installer.https_sources(raw)

    def test_two_known_blocks_convert_to_https_only(self):
        self.assertEqual(installer.https_sources(sources()), sources('https'))

    def test_https_is_idempotent(self):
        once = installer.https_sources(sources('https'))
        self.assertEqual(installer.https_sources(once), once)

    def test_signature_configuration_preserved(self):
        output = installer.https_sources(sources())
        self.assertEqual(output.count('Signed-By: ' + installer.KEYRING), 2)
        self.assertNotIn('Trusted:', output)
        self.assertNotIn('Allow-Insecure:', output)
        self.assertNotIn('http://', output)

    def test_unknown_hosts_and_lookalikes_rejected(self):
        for host in ('example.com', 'deb.debian.org.evil.invalid', 'deb.debian.org:80',
                     'user@deb.debian.org'):
            with self.subTest(host=host):
                self.reject(sources().replace('deb.debian.org', host, 1))

    def test_unknown_or_extra_suites_rejected(self):
        for suites in ('bookworm bookworm-updates', 'trixie', 'trixie trixie-updates sid'):
            with self.subTest(suites=suites):
                self.reject(sources().replace('trixie trixie-updates', suites))
        self.reject(sources().replace('Suites: trixie-security', 'Suites: trixie'))

    def test_trust_override_fields_rejected(self):
        for field in ('Trusted: yes', 'Allow-Insecure: yes', 'Check-Valid-Until: no',
                      'Allow-Weak: yes', 'Enabled: no'):
            with self.subTest(field=field):
                self.reject(sources().replace('Types: deb', 'Types: deb\n' + field, 1))

    def test_alternate_or_missing_keyring_rejected(self):
        self.reject(sources().replace(installer.KEYRING, '/tmp/untrusted.gpg', 1))
        self.reject(sources().replace('Signed-By: ' + installer.KEYRING + '\n', '', 1))

    def test_duplicate_fields_rejected(self):
        for field in ('Types: deb', 'URIs: http://deb.debian.org/debian',
                      'Signed-By: ' + installer.KEYRING):
            with self.subTest(field=field):
                self.reject(sources().replace(field, field + '\n' + field, 1))

    def test_additional_repository_block_rejected(self):
        self.reject(sources() + '\nTypes: deb\nURIs: https://example.com/debian\n'
                    'Suites: trixie\nComponents: main\nSigned-By: ' + installer.KEYRING + '\n')

    def test_duplicate_repository_instead_of_security_rejected(self):
        first = sources().split('\n\n')[0]
        self.reject(first + '\n\n' + first + '\n')

    def test_multiple_uris_or_unexpected_paths_rejected(self):
        for uri in ('http://deb.debian.org/debian https://example.com/debian',
                    'http://deb.debian.org/debian/', 'http://deb.debian.org/other',
                    'http://deb.debian.org/debian?x=1'):
            with self.subTest(uri=uri):
                self.reject(sources().replace('http://deb.debian.org/debian\n', uri + '\n', 1))

    def test_unexpected_types_or_components_rejected(self):
        self.reject(sources().replace('Types: deb', 'Types: deb deb-src', 1))
        self.reject(sources().replace('Components: main', 'Components: main non-free', 1))

    def test_comments_do_not_change_configuration(self):
        self.assertEqual(installer.https_sources('# known repos\n' + sources()), sources('https'))

    def test_nonstring_oversize_partial_or_continuation_rejected(self):
        for raw in (None, b'data', 'x' * 65537, '', sources().split('\n\n')[0],
                    sources().replace('Suites:', ' Suites:', 1)):
            with self.subTest(type_name=type(raw).__name__):
                self.reject(raw)


if __name__ == '__main__':
    unittest.main()

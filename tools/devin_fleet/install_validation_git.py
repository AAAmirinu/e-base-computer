"""Image-build-only Git installation; never run on host/outer/model VM.

The build driver must pin the parent image and temporarily scope validation-VM
network access to deb.debian.org:443. APT signature/TLS verification stays enabled.
"""
import json
from pathlib import Path
import platform
import subprocess

KEYRING = '/usr/share/keyrings/debian-archive-keyring.pgp'


def https_sources(raw):
    if not isinstance(raw, str) or len(raw) > 65536:
        raise ValueError('Bounded Debian sources required')
    blocks, current = [], {}
    for line in [*raw.splitlines(), '']:
        if line.startswith('#'):
            continue
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        if line[0].isspace() or ':' not in line:
            raise ValueError('Unexpected source syntax')
        key, value = line.split(':', 1)
        if key in current:
            raise ValueError('Duplicate source field')
        current[key] = value.strip()
    if len(blocks) != 2:
        raise ValueError('Exactly two known Debian source blocks required')
    expected = {
        '/debian': {'trixie', 'trixie-updates'},
        '/debian-security': {'trixie-security'},
    }
    seen = set()
    output = []
    for block in blocks:
        if (set(block) != {'Types', 'URIs', 'Suites', 'Components', 'Signed-By'}
                or block['Types'] != 'deb' or block['Components'] != 'main'
                or block['Signed-By'] != KEYRING):
            raise ValueError('Unexpected trust or repository settings')
        uri = block['URIs']
        prefix = next((p for p in ('http://deb.debian.org', 'https://deb.debian.org')
                       if uri.startswith(p + '/')), None)
        path = uri[len(prefix):] if prefix else None
        if path not in expected or path in seen or set(block['Suites'].split()) != expected[path]:
            raise ValueError('Unexpected source host, path or suite')
        seen.add(path)
        output.append('\n'.join(('Types: deb', 'URIs: https://deb.debian.org' + path,
                                  'Suites: ' + block['Suites'], 'Components: main', 'Signed-By: ' + KEYRING)))
    return '\n\n'.join(output) + '\n'


def main():
    release = platform.freedesktop_os_release()
    if release.get('ID') != 'debian' or release.get('VERSION_CODENAME') != 'trixie':
        raise RuntimeError('Pinned Debian trixie build required')
    sources = Path('/etc/apt/sources.list.d/debian.sources')
    if sources.is_symlink() or not sources.is_file():
        raise RuntimeError('Regular Debian sources file required')
    if set(p.name for p in sources.parent.iterdir()) != {'debian.sources'}:
        raise RuntimeError('Additional sources not authorized')
    legacy = Path('/etc/apt/sources.list')
    if legacy.exists() and legacy.read_text().strip():
        raise RuntimeError('Additional legacy sources not authorized')
    converted = https_sources(sources.read_text())
    sources.write_text(converted)
    subprocess.run(['/usr/bin/apt-get', 'update'], check=True, timeout=120)
    subprocess.run(['/usr/bin/apt-get', 'install', '-y', '--no-install-recommends', 'git'],
                   check=True, timeout=180)
    versions = subprocess.run(['/usr/bin/dpkg-query', '-W', '-f=${Package}=${Version}\n', 'git', 'git-man'],
                              check=True, capture_output=True, text=True, timeout=15).stdout.splitlines()
    output = Path('/usr/local/share/e-base')
    output.mkdir(parents=True, exist_ok=True)
    (output/'git-build.json').write_text(json.dumps(dict(schema=1, packages=versions,
        apt_host='deb.debian.org', transport='https', signature_checks_overridden=False), sort_keys=True))
    subprocess.run(['/usr/bin/apt-get', 'clean'], check=True, timeout=30)


if __name__ == '__main__':
    main()

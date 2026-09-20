"""Fixed guest policy source, embedded by the trusted controller. No execution here."""
SOURCE = r'''
def read_git_args(args):
    allowed = (
        ['rev-parse', 'HEAD'], ['rev-parse', 'HEAD^{tree}'], ['ls-files', '-z'],
        ['ls-files', '--others', '--exclude-standard', '-z'],
        ['diff', '--no-renames', '--name-only', '-z', 'HEAD'])
    if args not in allowed:
        raise ValueError('Model-phase Git command not admitted')
    if args[0] == 'diff':
        return ['diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=all', *args[1:]]
    return list(args)

def check_read_git_config(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 65536 or not raw.endswith(b'\0'):
        raise ValueError('Bounded effective Git configuration required')
    fixed = {b'core.repositoryformatversion': b'0', b'core.filemode': b'true',
             b'core.bare': b'false', b'core.logallrefupdates': b'true'}
    data = {b'user.name', b'user.email', b'remote.origin.url',
            b'remote.origin.fetch', b'remote.origin.pushurl'}
    seen = set()
    for entry in raw[:-1].split(b'\0'):
        key, sep, value = entry.partition(b'\n')
        if not sep or key in seen or b'\n' in value or b'\r' in value or len(value) > 4096:
            raise ValueError('Ambiguous Git configuration')
        seen.add(key)
        if key in fixed:
            if value != fixed[key]:
                raise ValueError('Unsupported core Git configuration')
        elif key not in data:
            raise ValueError('Git configuration outside read-only contract')
    if not set(fixed) <= seen:
        raise ValueError('Missing fresh repository core configuration')
'''

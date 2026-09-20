"""Read-only verifier for the exact physical-PC reboot evidence pair."""
import hashlib
import json
from pathlib import Path
import re

import production_registration_prepare
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _file

ROOT = Path('/home/fleet/controller-validation/physical-reboot-v1')
EXPECTED_CANDIDATE = '7721e6c83db493406ea71a3e0e965d4cdc287a13aa1679dbe67d3259d75fb682'


def _load(name):
    raw = _file(ROOT / name, 65536)
    return raw, json.loads(raw, object_pairs_hook=_pairs)


def inspect():
    pre_raw, pre = _load('pre.json')
    _, post = _load('post.json')
    prepared = production_registration_prepare.inspect()
    uuid = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    false_keys = ('automatic_resume', 'activated', 'published')
    if (set(path.name for path in ROOT.iterdir()) != {'pre.json', 'post.json'}
            or pre.get('schema') != 1 or pre.get('phase') != 'prepared'
            or post.get('schema') != 1 or post.get('phase') != 'verified'
            or pre.get('probe_id') != post.get('probe_id')
            or re.fullmatch(uuid, str(pre.get('probe_id'))) is None
            or pre.get('candidate_sha256') != EXPECTED_CANDIDATE
            or post.get('candidate_sha256') != EXPECTED_CANDIDATE
            or prepared.get('candidate_sha256') != EXPECTED_CANDIDATE
            or post.get('pre_sha256') != hashlib.sha256(pre_raw).hexdigest()
            or type(pre.get('windows_boot_filetime_utc')) is not int
            or type(post.get('before_windows_boot_filetime_utc')) is not int
            or type(post.get('after_windows_boot_filetime_utc')) is not int
            or pre.get('windows_boot_filetime_utc') != post.get('before_windows_boot_filetime_utc')
            or post.get('after_windows_boot_filetime_utc') <= post.get('before_windows_boot_filetime_utc')
            or pre.get('wsl_boot_id') != post.get('before_wsl_boot_id')
            or post.get('after_wsl_boot_id') == post.get('before_wsl_boot_id')
            or pre.get('all_vms_stopped') is not True
            or post.get('all_vms_stopped') is not True
            or any(record.get(key) is not False for record in (pre, post) for key in false_keys)
            or re.fullmatch(r'[0-9a-f]{64}', str(pre.get('readiness_sha256'))) is None
            or pre.get('readiness_sha256') != post.get('readiness_sha256')):
        raise ValueError('Exact physical reboot evidence required')
    return {'verified': True, 'probe_id': pre['probe_id'],
            'candidate_sha256': EXPECTED_CANDIDATE,
            'before_windows_boot_filetime_utc': post['before_windows_boot_filetime_utc'],
            'after_windows_boot_filetime_utc': post['after_windows_boot_filetime_utc'],
            'all_vms_stopped': True, 'automatic_resume': False,
            'activated': False, 'published': False}

"""Create and inspect an inert, one-shot sibling trial-controller state."""
import hashlib
import json
from turn_validation_result import same_json
import os
from pathlib import Path

from durable import _sync_directory
from managed_cli_guard import require_managed_namespace
from process_control import global_lock_held
import production_registration_prepare
from validation_dispatch_receipt import _pairs
from validation_snapshot_input import _directory, _file


ROOT = production_registration_prepare.ROOT
PREVIOUS_RUN = ROOT / 'production-registration-trial-v10'
RUN = ROOT / 'production-registration-trial-v11'
STATE = RUN / 'state'
CONTROLLER = RUN / 'controller'
_STATE_FILES = {
    'status.json', 'source-registry.json', 'candidate.json',
    'registration.json', 'binding.json', 'commit.json',
}
_CONTROLLER_DIRS = {'cycles', 'operations', 'model-turn-fences'}
_RUNTIME_DIRS = _CONTROLLER_DIRS | {
    'candidate-review', 'seed', 'seed-v2', 'seed-inspect-v1', 'seed-v3',
    'seed-v3-diagnostic',
    'seed-v3-diagnostic-v2',
    'seed-v4',
    'seed-v5',
    'seed-v6',
    'seed-v7',
    'seed-v8',
    'seed-v9',
    'seed-v10',
    'seed-v11',
    'seed-v12',
}


def _raw(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _exclusive(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _mkdir(path):
    os.mkdir(path, 0o700)
    _sync_directory(path.parent)


def _four_hashes(source_raw, candidate_raw, registration_raw, active_raw):
    return {
        'source_sha256': _sha(source_raw),
        'candidate_sha256': _sha(candidate_raw),
        'registration_sha256': _sha(registration_raw),
        'active_registry_sha256': _sha(active_raw),
    }


def prepare():
    """Reserve the fixed trial tree once; partial state is never resumed."""
    require_managed_namespace()
    if not global_lock_held('/tmp/e-base-devin-fleet-global.lock'):
        raise ValueError('Global controller lock required')
    prepared = production_registration_prepare.inspect()
    _directory(ROOT)
    prior_state=_file(PREVIOUS_RUN/'state'/'commit.json',65536)
    prior_cycle=_file(PREVIOUS_RUN/'controller'/'cycles'/'fixed-inert-one-turn-v11'/'cycle.json',65536)
    prior_value=json.loads(prior_cycle,object_pairs_hook=_pairs)
    if (prior_value.get('phase')!='held' or prior_value.get('interrupted_phase')!='model_pending'
            or prior_value.get('error_type')!='ValueError' or prior_value.get('published') is not False
            or prior_value.get('model_retry_allowed') is not False
            or prior_value.get('resume_available') is not False):
        raise ValueError('Exact prior held trial evidence required')

    prep_run = production_registration_prepare.RUN
    source_raw = _file(prep_run / 'source-registry.json', 65536)
    candidate_raw = _file(prep_run / 'candidate.json', 65536)
    active_path = ROOT / 'sandbox-registry.json'
    active_before = active_path.stat()
    active_raw = _file(active_path, 65536)
    source = json.loads(source_raw, object_pairs_hook=_pairs)
    candidate = json.loads(candidate_raw, object_pairs_hook=_pairs)
    active = json.loads(active_raw, object_pairs_hook=_pairs)
    if (active_raw != source_raw or active != source
            or active.get('production_enabled') is not False
            or prepared['source_sha256'] != _sha(source_raw)
            or prepared['candidate_sha256'] != _sha(candidate_raw)
            or candidate.get('migration_epoch') != prepared['migration_epoch']):
        raise ValueError('Prepared candidate source or active registry mismatch')

    _mkdir(RUN)
    _mkdir(STATE)
    _mkdir(CONTROLLER)
    for name in sorted(_CONTROLLER_DIRS):
        _mkdir(CONTROLLER / name)
    status = {
        'schema': 1, 'phase': 'preparing', 'automatic_resume': False,
        'retry': False, 'activated': False, 'published': False,
    }
    _exclusive(STATE / 'status.json', _raw(status))
    _exclusive(STATE / 'source-registry.json', source_raw)
    _exclusive(STATE / 'candidate.json', candidate_raw)
    registration = dict(candidate)
    registration['controller_root'] = str(CONTROLLER)
    registration_raw = _raw(registration)
    _exclusive(STATE / 'registration.json', registration_raw)
    hashes = _four_hashes(source_raw, candidate_raw, registration_raw, active_raw)
    binding = dict(
        {'schema': 1, 'migration_epoch': candidate['migration_epoch'],
         'automatic_resume': False, 'retry': False, 'activated': False,
         'published': False,
         'prior_state_sha256':_sha(prior_state),
         'prior_cycle_sha256':_sha(prior_cycle)}, **hashes)
    binding_raw = _raw(binding)
    _exclusive(STATE / 'binding.json', binding_raw)

    active_after = active_path.stat()
    stamp = lambda value: (value.st_dev, value.st_ino, value.st_mode,
                           value.st_uid, value.st_nlink, value.st_size)
    if (_file(active_path, 65536) != active_raw
            or stamp(active_before) != stamp(active_after)
            or _file(prep_run / 'source-registry.json', 65536) != source_raw
            or _file(prep_run / 'candidate.json', 65536) != candidate_raw):
        raise ValueError('Prepared state changed during trial reservation')
    commit = dict(binding, phase='complete', binding_sha256=_sha(binding_raw))
    _exclusive(STATE / 'commit.json', _raw(commit))
    return inspect()


def inspect(*, runtime=False):
    """Fail closed on any extra entry, symlink, raw drift, or source drift."""
    if type(runtime) is not bool:
        raise ValueError('Explicit trial inspection phase required')
    require_managed_namespace()
    prepared = production_registration_prepare.inspect()
    for path in (ROOT, RUN, STATE, CONTROLLER):
        _directory(path)
    if set(os.listdir(RUN)) != {'state', 'controller'}:
        raise ValueError('Exact trial root entries required')
    if set(os.listdir(STATE)) != _STATE_FILES:
        raise ValueError('Exact trial state files required')
    controller_entries=set(os.listdir(CONTROLLER))
    if (not runtime and controller_entries != _CONTROLLER_DIRS) or (
            runtime and (not _CONTROLLER_DIRS <= controller_entries
                         or not controller_entries <= _RUNTIME_DIRS)):
        raise ValueError('Exact trial controller entries required')
    for name in _CONTROLLER_DIRS:
        path = CONTROLLER / name
        _directory(path)
        if not runtime and os.listdir(path):
            raise ValueError('Trial controller directory not empty')
    if 'candidate-review' in controller_entries:
        _directory(CONTROLLER/'candidate-review')
    if 'seed' in controller_entries:
        _directory(CONTROLLER/'seed')
    if 'seed-v2' in controller_entries:
        _directory(CONTROLLER/'seed-v2')
    if 'seed-inspect-v1' in controller_entries:
        _directory(CONTROLLER/'seed-inspect-v1')
    if 'seed-v3' in controller_entries:
        _directory(CONTROLLER/'seed-v3')
    if 'seed-v3-diagnostic' in controller_entries:
        _directory(CONTROLLER/'seed-v3-diagnostic')
    if 'seed-v3-diagnostic-v2' in controller_entries:
        _directory(CONTROLLER/'seed-v3-diagnostic-v2')
    if 'seed-v4' in controller_entries:
        _directory(CONTROLLER/'seed-v4')
    if 'seed-v5' in controller_entries:
        _directory(CONTROLLER/'seed-v5')
    if 'seed-v6' in controller_entries:
        _directory(CONTROLLER/'seed-v6')
    if 'seed-v7' in controller_entries:
        _directory(CONTROLLER/'seed-v7')
    if 'seed-v8' in controller_entries:
        _directory(CONTROLLER/'seed-v8')
    if 'seed-v9' in controller_entries:
        _directory(CONTROLLER/'seed-v9')
    if 'seed-v10' in controller_entries:
        _directory(CONTROLLER/'seed-v10')
    if 'seed-v11' in controller_entries:
        _directory(CONTROLLER/'seed-v11')
    if 'seed-v12' in controller_entries:
        _directory(CONTROLLER/'seed-v12')
    status = json.loads(_file(STATE / 'status.json', 65536), object_pairs_hook=_pairs)
    source_raw = _file(STATE / 'source-registry.json', 65536)
    candidate_raw = _file(STATE / 'candidate.json', 65536)
    registration_raw = _file(STATE / 'registration.json', 65536)
    binding_raw = _file(STATE / 'binding.json', 65536)
    commit_raw = _file(STATE / 'commit.json', 65536)
    source = json.loads(source_raw, object_pairs_hook=_pairs)
    candidate = json.loads(candidate_raw, object_pairs_hook=_pairs)
    registration = json.loads(registration_raw, object_pairs_hook=_pairs)
    binding = json.loads(binding_raw, object_pairs_hook=_pairs)
    commit = json.loads(commit_raw, object_pairs_hook=_pairs)
    expected_status = {
        'schema': 1, 'phase': 'preparing', 'automatic_resume': False,
        'retry': False, 'activated': False, 'published': False,
    }
    active_raw = _file(ROOT / 'sandbox-registry.json', 65536)
    hashes = _four_hashes(source_raw, candidate_raw, registration_raw, active_raw)
    expected_binding = dict(
        {'schema': 1, 'migration_epoch': candidate.get('migration_epoch'),
         'automatic_resume': False, 'retry': False, 'activated': False,
         'published': False,
         'prior_state_sha256':_sha(_file(PREVIOUS_RUN/'state'/'commit.json',65536)),
         'prior_cycle_sha256':_sha(_file(PREVIOUS_RUN/'controller'/'cycles'/'fixed-inert-one-turn-v11'/'cycle.json',65536))}, **hashes)
    expected_commit = dict(expected_binding, phase='complete',
                           binding_sha256=_sha(binding_raw))
    derived = dict(candidate)
    derived['controller_root'] = str(CONTROLLER)
    prep_run = production_registration_prepare.RUN
    if (status != expected_status or binding != expected_binding
            or commit != expected_commit or registration != derived
            or registration_raw != _raw(derived)
            or candidate_raw != _file(prep_run / 'candidate.json', 65536)
            or source_raw != _file(prep_run / 'source-registry.json', 65536)
            or source_raw != active_raw
            or source.get('production_enabled') is not False
            or prepared['source_sha256'] != hashes['source_sha256']
            or prepared['candidate_sha256'] != hashes['candidate_sha256']
            or prepared['migration_epoch'] != candidate.get('migration_epoch')):
        raise ValueError('Trial state binding mismatch')
    return dict(expected_binding, prepared=True, phase='complete',
                controller_root=str(CONTROLLER))


def trial_guest_root():
    binding=inspect(runtime=True)
    digest=binding.get('candidate_sha256')
    if type(digest) is not str or len(digest)!=64:
        raise ValueError('Exact candidate digest required for trial guest root')
    return '/home/agent/e-base-trials/'+digest+'/machine-v12'


def runtime_registration():
    """Revalidate immutable bindings while allowing one trial's durable records."""
    inspect(runtime=True)
    value=json.loads(_file(STATE/'registration.json',65536),object_pairs_hook=_pairs)
    if value.get('controller_root')!=str(CONTROLLER):
        raise ValueError('Derived trial registration changed')
    return value


def check_runtime_registration(observed):
    """Admission callback: None means the frozen derived registration still matches."""
    current=runtime_registration()
    frozen=json.loads(json.dumps(observed,allow_nan=False))
    if type(frozen) is not dict or not same_json(frozen,current):
        raise ValueError('Observed trial registration changed')

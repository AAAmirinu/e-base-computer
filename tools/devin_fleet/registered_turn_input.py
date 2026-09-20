"""Read bounded, controller-owned turn inputs; never start a VM or change state."""
import hashlib
import json
import os
from pathlib import Path
import re

from sandbox_runtime import ROLES
from validation_snapshot_input import _directory, _file
from validation_dispatch_receipt import _pairs

ROOT = Path('/home/fleet/controller-validation')
FIELDS = {'schema','role','project_root','sequence','entry','state','settings',
          'parent_ref','parent_bundle_sha256'}


def _json(raw):
    def reject(value):
        raise ValueError('Nonfinite JSON refused')
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject)


def load(identity):
    if type(identity) is not str or re.fullmatch('[0-9a-f]{32}', identity) is None:
        raise ValueError('Fixed turn input identity required')
    _directory(ROOT)
    inputs = ROOT/'turn-inputs'
    _directory(inputs)
    directory = inputs/identity
    _directory(directory)
    registry_path = ROOT/'sandbox-registry.json'
    registry_raw = _file(registry_path, 65536)
    registration = _json(registry_raw)
    if type(registration) is not dict or registration.get('production_enabled') is not True:
        raise ValueError('Existing production registration required')
    value = registration.get('controller_root')
    if type(value) is not str:
        raise ValueError('Registered controller root required')
    root = Path(value)
    if root.parent != ROOT or re.fullmatch('production-[0-9a-f]{32}',root.name) is None:
        raise ValueError('Production root must be below controller root')
    _directory(root)
    cycles = root/'cycles'
    _directory(cycles)
    if os.path.lexists(root/'STOP') or os.path.lexists(cycles/identity):
        raise ValueError('Stopped or previously reserved turn')
    request_path = directory/'request.json'
    raw = _file(request_path, 1048576)
    request = _json(raw)
    if (type(request) is not dict or set(request) != FIELDS
            or type(request['schema']) is not int or request['schema'] != 1
            or type(request['role']) is not str or request['role'] not in ROLES
            or request['role'] not in registration.get('roles',{})
            or type(request['sequence']) is not int or not 0 <= request['sequence'] <= 2**53-1
            or any(type(request[k]) is not dict for k in ('entry','state','settings'))
            or type(request['parent_ref']) is not str
            or re.fullmatch(r'refs/heads/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',request['parent_ref']) is None
            or type(request['parent_bundle_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}',request['parent_bundle_sha256']) is None
            or type(request['project_root']) is not str):
        raise ValueError('Exact bounded turn request required')
    project = Path(request['project_root'])
    if root not in project.parents:
        raise ValueError('Project must be within registered root')
    _directory(project)
    bundle = _file(directory/'parent.bundle',16*1024*1024)
    if not bundle or hashlib.sha256(bundle).hexdigest() != request['parent_bundle_sha256']:
        raise ValueError('Parent bundle digest mismatch')
    if (_file(registry_path,65536) != registry_raw or _file(request_path,1048576) != raw
            or _file(directory/'parent.bundle',16*1024*1024) != bundle):
        raise ValueError('Turn inputs changed during read')
    return dict(registration=registration,controller_root=root,project_root=project,
        role=request['role'],entry=request['entry'],state=request['state'],settings=request['settings'],
        cycle_directory=cycles/identity,sequence=request['sequence'],parent_bundle=bundle,
        parent_bundle_sha256=request['parent_bundle_sha256'],parent_ref=request['parent_ref'])

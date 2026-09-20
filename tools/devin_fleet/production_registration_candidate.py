"""Build an inert production-registration candidate; never activate or write it."""
import json
from pathlib import Path
import re
import uuid

from sandbox_runtime import ROLES
from candidate_turn_admission import IMAGE as VALIDATION_IMAGE

ROOT = Path('/home/fleet/controller-validation')
ROLE_IMAGE = 'sha256:df7d566115e4d16b23a0477be5677ea0eb569de027bc1933238859a6f62293fd'


def compose(current, *, root_identity, migration_epoch):
    current = json.loads(json.dumps(current, allow_nan=False))
    legacy={'schema','distro','user','resources_per_sandbox','roles',
            'simultaneous_capacity_verified','production_enabled'}
    if (type(current) is not dict or set(current) != legacy
            or type(current.get('schema')) is not int or current['schema'] != 1
            or current.get('production_enabled') is not False
            or current.get('distro') != 'EBase-Sandboxes' or current.get('user') != 'fleet'
            or current.get('resources_per_sandbox') != {'cpus':2,'memory':'4g'}
            or type(current.get('simultaneous_capacity_verified')) is not int
            or current['simultaneous_capacity_verified'] != 1
            or set(current.get('roles',{})) != set(ROLES)):
        raise ValueError('Exact validated nonproduction registration required')
    for role, entry in current['roles'].items():
        if (type(entry) is not dict or set(entry) != {'id','name'}
                or entry['name'] != 'e-base-'+role
                or type(entry['id']) is not str or str(uuid.UUID(entry['id'])) != entry['id']):
            raise ValueError('Exact existing role identity required')
    if (type(root_identity) is not str or re.fullmatch('[0-9a-f]{32}',root_identity) is None
            or type(migration_epoch) is not str
            or str(uuid.UUID(migration_epoch)) != migration_epoch):
        raise ValueError('Explicit production root and migration identity required')
    candidate = dict(current,backend='sandbox')
    candidate.update(production_enabled=True,
        controller_root=str(ROOT/('production-'+root_identity)),
        validation_image_id=VALIDATION_IMAGE,
        migration_epoch=migration_epoch)
    candidate['roles']={role:dict(entry,image_digest=ROLE_IMAGE)
                        for role,entry in current['roles'].items()}
    validate(candidate)
    return candidate


def validate(value):
    required={'schema','backend','distro','user','resources_per_sandbox','roles',
              'simultaneous_capacity_verified','production_enabled','controller_root',
              'validation_image_id','migration_epoch'}
    if (type(value) is not dict or set(value) != required
            or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('production_enabled') is not True or value.get('backend') != 'sandbox'
            or value.get('distro') != 'EBase-Sandboxes' or value.get('user') != 'fleet'
            or value.get('resources_per_sandbox') != {'cpus':2,'memory':'4g'}
            or type(value.get('simultaneous_capacity_verified')) is not int
            or value['simultaneous_capacity_verified'] != 1
            or value.get('validation_image_id') != VALIDATION_IMAGE
            or type(value.get('migration_epoch')) is not str
            or str(uuid.UUID(value['migration_epoch'])) != value['migration_epoch']
            or set(value.get('roles',{})) != set(ROLES)):
        raise ValueError('Invalid production registration candidate')
    root=Path(value.get('controller_root',''))
    if root.parent != ROOT or re.fullmatch('production-[0-9a-f]{32}',root.name) is None:
        raise ValueError('Dedicated production root required')
    identities=set()
    for role,entry in value['roles'].items():
        if (type(entry) is not dict or set(entry) != {'id','name','image_digest'}
                or entry['name']!='e-base-'+role or entry['image_digest']!=ROLE_IMAGE
                or type(entry['id']) is not str or str(uuid.UUID(entry['id']))!=entry['id']
                or entry['id'] in identities):
            raise ValueError('Pinned unique role registration required')
        identities.add(entry['id'])
    return value

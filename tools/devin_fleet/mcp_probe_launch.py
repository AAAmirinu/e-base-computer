"""Reserved guest-only launch integration; no public/automatic entry point.

Caller must hold the fleet lock, verify the machine VM and inherited MCP config,
open only the approved network window, and finally close network and stop the VM.
The default catalog command is fresh, same-guest, time/output bounded. Optional
catalog_check is a trusted test adapter, never a model-controlled callback.
This module never grants production admission or claims all children stopped.
"""
from datetime import datetime, timezone
import json
import hashlib
import os
import re
import stat
import time

from machine_cli_smoke import CLI
from model_catalog_policy import MODEL, EXPIRY, require_free_model, _unique, _reject_constant
from mcp_probe_process import run_private_process
from mcp_probe_reservation import CLAIM, _private_directory, _exclusive_file
from mcp_probe_snapshot import _read, snapshot
from mcp_override_probe import read_global
from mcp_probe_catalog import read_catalog
from mcp_probe_supervision import consume as consume_supervision, require_unused, MARKER
from mcp_cli_identity import verify_cli


def _json(raw):
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)


def check_inherited(inputs):
    expected=inputs['inherited-mcp.sha256']
    if re.fullmatch(b'[0-9a-f]{64}\n',expected) is None:
        raise ValueError('Inherited configuration is not bound')
    if hashlib.sha256(read_global('mcp_config.json')).hexdigest().encode()+b'\n'!=expected:
        raise ValueError('Inherited MCP configuration changed')


def check_main_config():
    raw=read_global('config.json')
    value=_json(raw)
    if type(value) is not dict or value.get('hooks',{})!={} or value.get('mcpServers',{})!={}:
        raise ValueError('No inherited hooks or pending MCP migration permitted')
    return hashlib.sha256(raw).hexdigest()


def launch_reserved(state_directory, *, catalog_check=None, supervised_check=None):
    # This callback belongs to the trusted live outer supervisor, not a saved
    # receipt or guest/model input. No public command currently supplies it.
    if supervised_check is not None and not callable(supervised_check):
        raise ValueError('Trusted live supervisor required')
    if catalog_check is not None and not callable(catalog_check):
        raise ValueError('Trusted fresh catalog command required')
    deadline = time.monotonic() + 180
    state = _private_directory(state_directory)
    claim = None
    try:
        try: os.stat('prepare-only',dir_fd=state,follow_symlinks=False)
        except FileNotFoundError:
            if supervised_check is not None: raise ValueError('Supervised preparation hold required')
        else:
            if supervised_check is None: raise ValueError('Offline preparation requires supervised admission')
        claim = os.open(CLAIM, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=state)
        info = os.fstat(claim)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Private durable claim required')
        locator = _json(_read(claim, 'attempt.json', 4096)[0])
        reservation_raw = _read(claim, 'reservation.json', 1048576)[0]
        reservation = _json(reservation_raw)
        if (type(locator) is not dict or set(locator) != {'nonce', 'work', 'phase'}
                or locator['phase'] != 'preparing' or type(locator['nonce']) is not str
                or re.fullmatch('[0-9a-f]{32}', locator['nonce']) is None
                or type(reservation) is not dict or reservation.get('nonce') != locator['nonce']
                or type(reservation.get('schema')) is not int or reservation['schema'] != 1
                or reservation.get('phase') != 'reserved'):
            raise ValueError('Prepared reservation binding required')
        # Refuse already-consumed claims even before another catalog query.
        try:
            os.stat('launch.json', dir_fd=claim, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('Reserved probe already attempted')
        require_unused(claim)
        work = locator['work']
        before = snapshot(work, reservation, stage='before')
        check_inherited(before['inputs'])
        main_digest=check_main_config()
        argv = [CLI, '--config', work + '/config.json', '--model', MODEL,
                '--permission-mode', 'normal', '--respect-workspace-trust', 'false',
                '--export', work + '/export.json', '--print', before['inputs']['prompt.txt'].decode('utf-8')]
        if datetime.now(timezone.utc)>=EXPIRY:
            raise ValueError('Campaign expired before catalog')
        verify_cli()
        supervision=None
        if supervised_check is not None:
            supervision=consume_supervision(state,claim,nonce=locator['nonce'],
                                             reservation_raw=reservation_raw,work=work,
                                             timeout=max(0,deadline-time.monotonic()),verify=supervised_check)
            # A supervisor check may take time. Revalidate before even the catalog CLI.
            before=snapshot(work,reservation,stage='before')
            check_inherited(before['inputs'])
            if check_main_config()!=main_digest or time.monotonic()>=deadline or datetime.now(timezone.utc)>=EXPIRY:
                raise ValueError('Admission expired or main configuration changed')
            if time.time()>=supervision['receipt']['expires_at']:
                raise ValueError('Supervisor admission expired before catalog')
        verify_cli()
        catalog_timeout=min(60,deadline-time.monotonic(),(EXPIRY-datetime.now(timezone.utc)).total_seconds())
        if supervision is not None:
            catalog_timeout=min(catalog_timeout,supervision['receipt']['expires_at']-time.time())
        if catalog_timeout<=0: raise ValueError('Admission expired before catalog spawn')
        catalog_raw, catalog_returncode = read_catalog(work,timeout=catalog_timeout) if catalog_check is None else catalog_check()
        catalog = require_free_model(catalog_raw, catalog_returncode, now=datetime.now(timezone.utc))
        launch = dict(nonce=locator['nonce'], phase='attempted', model=MODEL,
                      main_config_sha256=main_digest,
                      catalog_sha256=catalog['catalog_sha256'], resume_used=False,
                      work=work, input_sha256=reservation['input_sha256'],
                      reservation_sha256=hashlib.sha256(reservation_raw).hexdigest(),
                      argv_sha256=hashlib.sha256(json.dumps(argv).encode()).hexdigest())
        if supervision is not None:
            launch['supervision']=supervision
        _exclusive_file(claim, 'launch.json', json.dumps(launch).encode())
        os.fsync(claim)
        # Never reset launch.json after any later failure, including spawn failure.
        before = snapshot(work, reservation, stage='before')
        check_inherited(before['inputs'])
        if check_main_config()!=main_digest:
            raise ValueError('Inherited main configuration changed during catalog')
        verify_cli()
        remaining = min((EXPIRY - datetime.now(timezone.utc)).total_seconds(), deadline-time.monotonic())
        if supervision is not None:
            if (_read(state,'prepare-only',1)[0]!=b''
                    or hashlib.sha256(_read(claim,MARKER,1048576)[0]).hexdigest()!=supervision['receipt_sha256']):
                raise ValueError('Supervised admission state changed')
            remaining=min(remaining,supervision['receipt']['expires_at']-time.time())
        if remaining <= 0:
            raise ValueError('Campaign expired before launch')
        result = run_private_process(argv, cwd=work, timeout=min(90, remaining))
        record = dict(result, nonce=locator['nonce'], phase='awaiting_vm_stop',
                      passed=False, production_admitted=False, resume_used=False)
        _exclusive_file(claim, 'process-result.json', json.dumps(record, allow_nan=False).encode())
        os.fsync(claim)
        return record
    finally:
        if claim is not None:
            os.close(claim)
        os.close(state)

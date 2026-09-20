"""Sanitized live catalog check using the existing role lease; no login/model."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import uuid

from managed_cli_guard import require_managed_namespace
from model_catalog_policy import MODEL, EXPIRY
from sandbox_repository import GuestRepository
from validation_snapshot_input import _file
from validation_dispatch_receipt import _pairs

ROOT = Path('/home/fleet/controller-validation')
PROBE = r'''
import json, os, selectors, subprocess, sys, time
exec(compile(sys.argv[1], '<trusted-catalog-policy>', 'exec'))
marker=sys.argv[2]
child=None
try:
    child=subprocess.Popen(['/home/agent/.local/bin/devin-cli','models','list','--format','json'],
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    selector=selectors.DefaultSelector()
    chunks=[]
    total=0
    try:
        selector.register(child.stdout,selectors.EVENT_READ,True)
        selector.register(child.stderr,selectors.EVENT_READ,False)
        deadline=time.monotonic()+float(sys.argv[3])
        while selector.get_map():
            if time.monotonic()>=deadline:
                raise TimeoutError('Catalog deadline')
            for event,_ in selector.select(.1):
                chunk=os.read(event.fileobj.fileno(),65536)
                if not chunk:
                    selector.unregister(event.fileobj)
                    continue
                total+=len(chunk)
                if total>1024*1024:
                    raise ValueError('Catalog output bound')
                if event.data:
                    chunks.append(chunk)
        result=require_free_model(b''.join(chunks),child.wait(timeout=max(.1,deadline-time.monotonic())),
                                  now=datetime.now(timezone.utc))
        print(marker+json.dumps(dict(catalog_verified=True,**result)),flush=True)
    finally:
        selector.close()
except Exception as error:
    print(marker+json.dumps(dict(catalog_verified=False,error_type=type(error).__name__)),flush=True)
finally:
    if child is not None:
        if child.poll() is None:
            child.kill()
        child.wait()
'''


def check_catalog(repo, *, timeout):
    require_managed_namespace()
    if not isinstance(repo, GuestRepository):
        raise ValueError('Active guest repository lease required')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('Finite remaining time required')
    available=min(timeout,(EXPIRY-datetime.now(timezone.utc)).total_seconds())
    cleanup_grace=15
    if available<=cleanup_grace:
        raise RuntimeError('Campaign deadline reached')
    seconds=min(available-cleanup_grace,60)
    transport_timeout=seconds+cleanup_grace
    source=_file(ROOT/'model_catalog_policy.py',32768).decode('utf-8')
    marker='EBASE_CATALOG_'+uuid.uuid4().hex+':'
    log=repo.log_dir/('catalog-'+uuid.uuid4().hex+'.log')
    try:
        completed=repo.controller.execute(['python3','-I','-c',PROBE,source,marker,str(seconds)],
            cwd='/',log_path=log,timeout=transport_timeout,max_log_bytes=65536,
            external_stop=repo.external_stop)
        if completed.returncode!=0:
            raise ValueError('Catalog probe command failed')
        raw=_file(log,65536)
        lines=[line[len(marker):] for line in raw.decode('utf-8').splitlines() if line.startswith(marker)]
        if len(lines)!=1:
            raise ValueError('Missing or ambiguous sanitized catalog result')
        result=json.loads(lines[0],object_pairs_hook=_pairs)
        if (not isinstance(result,dict) or set(result)!={'catalog_verified','model_uid','cost_tier',
                'catalog_sha256','model_executed','authentication_verified'}
                or result['catalog_verified'] is not True or result['model_uid']!=MODEL
                or result['cost_tier']!='Free' or result['model_executed'] is not False
                or result['authentication_verified'] is not False
                or not isinstance(result['catalog_sha256'],str)
                or re.fullmatch('[0-9a-f]{64}',result['catalog_sha256']) is None
                or datetime.now(timezone.utc)>=EXPIRY):
            raise ValueError('Free catalog not verified; no fallback')
        return result
    except BaseException:
        repo.controller.stop()
        raise

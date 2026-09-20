"""Bounded read-only identity check of the reviewed installed CLI executable."""
import hashlib
import os
import stat
import re

CLI='/home/agent/.local/bin/devin-cli'
PIN='9926e1e6e0f3071398759efd1414609a8a54762d08a01bb301f4407d1caccf5a'
STORAGE='/home/agent/.local/share/devin/cli/_versions'
TARGET=STORAGE+'/current/bin/devin'


def _verify(path,expected):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid not in (0,os.getuid())
                or before.st_mode & 0o022 or not before.st_mode & 0o111
                or not 0<before.st_size<=256*1024*1024):
            raise ValueError('Protected bounded CLI executable required')
        digest=hashlib.sha256(); count=0
        while True:
            raw=os.read(fd,1048576)
            if not raw: break
            count+=len(raw)
            if count>256*1024*1024: raise ValueError('CLI size bound exceeded')
            digest.update(raw)
        after=os.fstat(fd); linked=os.stat(path,follow_symlinks=False)
        def stamp(info):
            return (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        if count!=before.st_size or stamp(before)!=stamp(after) or stamp(after)!=stamp(linked):
            raise ValueError('CLI changed during identity check')
        if digest.hexdigest()!=expected: raise ValueError('Reviewed CLI identity mismatch')
        return expected
    finally: os.close(fd)


def _verify_install(cli,target,storage,pin):
    cli,target,storage=map(os.fspath,(cli,target,storage))
    link=os.lstat(cli)
    if not stat.S_ISLNK(link.st_mode) or link.st_uid not in (0,os.getuid()) or os.readlink(cli)!=target:
        raise ValueError('Exact reviewed CLI installation link required')
    parent=os.stat(os.path.dirname(cli),follow_symlinks=False)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid not in (0,os.getuid()) or parent.st_mode & 0o022:
        raise ValueError('Protected CLI link directory required')
    if os.path.realpath(storage,strict=True)!=storage:
        raise ValueError('Canonical CLI storage root required')
    resolved=os.path.realpath(target,strict=True)
    if os.path.commonpath((storage,resolved))!=storage:
        raise ValueError('CLI target escapes reviewed storage')
    directory=os.path.dirname(resolved)
    while True:
        info=os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,os.getuid()) or info.st_mode & 0o022:
            raise ValueError('Protected CLI storage directory required')
        if directory==storage: break
        directory=os.path.dirname(directory)
    result=_verify(resolved,pin)
    after=os.lstat(cli)
    def link_stamp(info):
        return (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    if (link_stamp(link)!=link_stamp(after) or os.readlink(cli)!=target or os.path.realpath(target,strict=True)!=resolved
            or os.path.realpath(storage,strict=True)!=storage):
        raise ValueError('CLI installation changed during verification')
    return result


def verify_cli(): return _verify_install(CLI,TARGET,STORAGE,PIN)


def inspect_link():
    """Fixed executable-link metadata only; do not open or execute the target."""
    info=os.lstat(CLI)
    if not stat.S_ISLNK(info.st_mode): raise ValueError('Expected installation symlink')
    target=os.readlink(CLI)
    if not 0<len(target)<=512 or re.fullmatch(r'[A-Za-z0-9_./-]+',target) is None:
        raise ValueError('Unrecognized executable path syntax')
    resolved=os.path.normpath(os.path.join(os.path.dirname(CLI),target))
    final=os.lstat(resolved)
    return dict(link_target=target,resolved_target=resolved,
                target_kind='regular' if stat.S_ISREG(final.st_mode) else 'symlink' if stat.S_ISLNK(final.st_mode) else 'other',
                target_owned=final.st_uid in (0,os.getuid()),target_protected=not bool(final.st_mode & 0o022),
                target_executable=bool(final.st_mode & 0o111),model_executed=False,identity_verified=False)


def validate_metadata(value):
    flags={'target_owned','target_protected','target_executable','model_executed','identity_verified'}
    if (type(value) is not dict or set(value)!=flags|{'link_target','resolved_target','target_kind'}
            or any(type(value[k]) is not bool for k in flags)
            or any(type(value[k]) is not str or not 0<len(value[k])<=512 or re.fullmatch(r'[A-Za-z0-9_./-]+',value[k]) is None
                   for k in ('link_target','resolved_target'))
            or value['target_kind'] not in ('regular','symlink','other')
            or value['model_executed'] is not False or value['identity_verified'] is not False):
        raise ValueError('Invalid executable metadata')
    return value


PROBE="import sys,json; scope={}; exec(sys.argv[1],scope); print('EBASE_CLI_LINK:'+json.dumps(scope['inspect_link']()))"

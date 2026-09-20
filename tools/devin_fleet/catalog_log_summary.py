"""Offline finite-vocabulary log inspection; never exports log text or names."""
import os
import re
import stat
from datetime import datetime,timezone

LOG_DIRECTORY='/home/agent/.local/share/devin/cli/logs'
START=datetime(2026,9,20,6,36,49,tzinfo=timezone.utc).timestamp()
END=datetime(2026,9,20,6,38,0,tzinfo=timezone.utc).timestamp()
PATTERNS={
    'tls_failure':rb'(tls|ssl|certificate)[^\n]{0,100}(error|fail|invalid|unknown issuer)',
    'dns_failure':rb'(dns|resolve)[^\n]{0,100}(error|fail)',
    'proxy_failure':rb'proxy[^\n]{0,100}(error|fail|refused)',
    'auth_rejection':rb'\b(unauthorized|unauthenticated|forbidden|token rejected)\b',
    'auth_unauthorized':rb'\bunauthorized\b',
    'auth_unauthenticated':rb'\bunauthenticated\b',
    'auth_forbidden':rb'\bforbidden\b',
    'auth_token_rejected':rb'\btoken rejected\b',
    'auth_login_required':rb'\b(not logged in|login required|log in required|sign in required)\b',
    'auth_token_expired':rb'\b(token expired|expired token|token has expired)\b',
    'http_401':rb'\b(status|status_code|http)[^\n]{0,24}\b401\b',
    'http_403':rb'\b(status|status_code|http)[^\n]{0,24}\b403\b',
    'subscription_or_entitlement':rb'\b(subscription|entitlement|seat|license)\b[^\n]{0,100}\b(denied|required|missing|expired|invalid)\b',
    'rate_or_quota':rb'\b(rate limit|rate limited|quota exceeded|resource exhausted)\b',
    'timeout':rb'\b(timed out|timeout|deadline exceeded)\b',
    'retry':rb'\b(retry|retrying|retries)\b',
    'connection_failure':rb'(connection refused|connection reset|connect error)',
    'error_level':rb'\bERROR\b',
}

# Co-occurrence on the rejection line only, not attribution to a request/process.
REJECTION_CONTEXT={
    'backend_host':rb'(?<![a-z0-9_.-])server\.codeium\.com(?![a-z0-9_.-])',
    'static_host':rb'(?<![a-z0-9_.-])static\.devin\.ai(?![a-z0-9_.-])',
    'feature_host':rb'(?<![a-z0-9_.-])unleash\.codeium\.com(?![a-z0-9_.-])',
    'api_host':rb'(?<![a-z0-9_.-])api\.devin\.ai(?![a-z0-9_.-])',
    'sentry':rb'\bsentry\b',
    'model_catalog':rb'\b(models|catalog|get_models|list_models|get_available_models)\b',
    'update':rb'\b(update|updater|updates|self_update|auto_update)\b',
    'feature_flags':rb'\b(unleash|feature_flags|feature flag|feature flags)\b',
    'proxy_policy':rb'\b(proxy|policy|sandbox|egress)\b',
    'authentication':rb'\b(authentication|authorize|auth|login|credentials)\b',
}
for _name in REJECTION_CONTEXT:PATTERNS['rejection_line_'+_name]=rb'(?!)'


def classify(raw):
    result={name:min(1000,len(re.findall(pattern,raw,re.IGNORECASE))) for name,pattern in PATTERNS.items()}
    for line in raw.splitlines():
        if not re.search(rb'\b(forbidden|403)\b',line,re.IGNORECASE):continue
        for name,pattern in REJECTION_CONTEXT.items():
            if re.search(pattern,line,re.IGNORECASE):
                key='rejection_line_'+name;result[key]=min(1000,result[key]+1)
    return result


def collect(directory=LOG_DIRECTORY):
    parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in directory.strip('/').split('/'):
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
        names=os.listdir(parent)
        if len(names)>1000:raise ValueError('Log directory entry limit')
        candidates=[]
        for name in names:
            if re.fullmatch(r'devin_[0-9TtZz_.:+-]{8,50}_[0-9]{1,12}\.log',name) is None:continue
            info=os.stat(name,dir_fd=parent,follow_symlinks=False)
            if START<=info.st_mtime<=END:candidates.append(name)
        if len(candidates)>8:raise ValueError('Log candidate limit')
        counts={name:0 for name in PATTERNS};total=0
        for name in candidates:
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                before=os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1
                        or before.st_mode&0o022 or before.st_size>4*1024*1024
                        or not START<=before.st_mtime<=END):
                    raise ValueError('Protected bounded regular log required')
                total+=before.st_size
                if total>8*1024*1024:raise ValueError('Total log limit')
                with os.fdopen(os.dup(fd),'rb') as stream:raw=stream.read(4*1024*1024+1)
                stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_uid,s.st_nlink)
                if (len(raw)!=before.st_size or stamp(before)!=stamp(os.fstat(fd))
                        or stamp(before)!=stamp(os.stat(name,dir_fd=parent,follow_symlinks=False))):
                    raise ValueError('Log changed during inspection')
                for key,value in classify(raw).items():counts[key]=min(1000,counts[key]+value)
            finally:os.close(fd)
        return dict(candidate_count=len(candidates),categories=counts,read_complete=True,
                    attempt_bound=False,raw_log_exported=False,credential_store_accessed=False,
                    secrets_extracted=False,cli_executed=False,model_executed=False)
    finally:os.close(parent)


PROBE='''import sys,json,types
try:
    m=types.ModuleType('trusted_logs')
    exec(compile(sys.argv[1],'<trusted_logs>','exec'),m.__dict__)
    value=m.collect()
except Exception:
    print('EBASE_LOG_SUMMARY_FAILED',flush=True)
    sys.exit(1)
print('EBASE_LOG_SUMMARY:'+json.dumps(value),flush=True)
'''

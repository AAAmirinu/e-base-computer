"""Versioned trusted fixture-source adapter; original evidence stays unchanged.

Supports bounded MCP string and integer request IDs. No live activation,
permission changes, argument relaxation, or model execution.
Unlike the original fixture, bounded protocol IDs are reflected in responses;
tool argument values are never reflected.
"""
import hashlib
OLD = """    if type(identity) is not int or not 0 <= identity <= 2**53-1:
        raise ValueError('Bounded numeric request id required')"""
NEW = """    if not ((type(identity) is int and -(2**53-1) <= identity <= 2**53-1)
            or (type(identity) is str and len(identity.encode('utf-8')) <= 128)):
        raise ValueError('Bounded string or integer request id required')"""

def compatible_source(raw):
    if type(raw) is not bytes or not 0<len(raw)<=16384:
        raise ValueError('Bounded trusted fixture source required')
    source=raw.decode('utf-8')
    if source.count(OLD)!=1 or NEW in source:
        raise ValueError('Trusted fixture ID guard drift')
    updated=source.replace(OLD,NEW,1)
    compile(updated,'<trusted-compatible-fixture>','exec')
    return updated.encode('utf-8')

def adapt_inputs(inputs):
    if type(inputs) is not dict or type(inputs.get('fixture.py')) is not bytes or type(inputs.get('runner.py')) is not bytes:
        raise ValueError('Trusted fixture and runner inputs required')
    old=inputs['fixture.py'];new=compatible_source(old)
    digest=hashlib.sha256(old).hexdigest().encode('ascii')
    runner=inputs['runner.py']
    if len(runner)>16384 or runner.count(digest)!=1:
        raise ValueError('Exact original fixture digest required')
    updated=runner.replace(digest,hashlib.sha256(new).hexdigest().encode('ascii'),1)
    compile(updated,'<trusted-compatible-runner>','exec')
    return dict(inputs,**{'fixture.py':new,'runner.py':updated})

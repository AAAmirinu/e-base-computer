"""Compose bounded controller-owned sources for a future independent profile.

Does not change the active control profile or import guest workspace code.
"""
def compose(control_source,compat_source):
    for source in (control_source,compat_source):
        if type(source) is not str or not 0<len(source.encode('utf-8'))<=16384:
            raise ValueError('Bounded trusted builder source required')
    result=(
        'import types as _types\n'
        '_control=_types.ModuleType("trusted_control_builder")\n'
        '_compat=_types.ModuleType("trusted_fixture_compat")\n'
        'exec(compile('+repr(control_source)+',"<trusted-control-builder>","exec"),_control.__dict__)\n'
        'exec(compile('+repr(compat_source)+',"<trusted-fixture-compat>","exec"),_compat.__dict__)\n'
        'def make_input_builder(raw):\n'
        '    baseline=_control.make_input_builder(raw)\n'
        '    return lambda work,nonce,identity: _compat.adapt_inputs(baseline(work,nonce,identity))\n'
        'def build_inputs(*args,**kwargs):\n'
        '    return _compat.adapt_inputs(_control.build_inputs(*args,**kwargs))\n')
    if len(result.encode('utf-8'))>16384:
        raise ValueError('Composed builder exceeds guest source limit')
    compile(result,'<trusted-compatible-control-builder>','exec')
    return result

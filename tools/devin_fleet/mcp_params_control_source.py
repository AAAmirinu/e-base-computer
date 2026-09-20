"""Offline, independent composition for the params-compatible fixture.

Never changes the consumed ID-only profile or resolves its adapter from a
guest import path. Only controller-supplied bounded sources are composed.
"""
IMPORT = 'from mcp_fixture_compat import adapt_inputs as id_inputs\n'


def compose(control_source, compat_source, params_source):
    for source in (control_source, compat_source, params_source):
        if type(source) is not str or not 0 < len(source.encode('utf-8')) <= 16384:
            raise ValueError('Bounded trusted builder source required')
    if params_source.count(IMPORT) != 1:
        raise ValueError('Trusted params dependency drift')
    params_source = params_source.replace(IMPORT, '', 1)
    result = (
        'import types as _types\n'
        '_control=_types.ModuleType("trusted_control_builder")\n'
        '_compat=_types.ModuleType("trusted_fixture_compat")\n'
        '_params=_types.ModuleType("trusted_fixture_params")\n'
        'exec(compile(' + repr(control_source) + ',"<trusted-control-builder>","exec"),_control.__dict__)\n'
        'exec(compile(' + repr(compat_source) + ',"<trusted-fixture-compat>","exec"),_compat.__dict__)\n'
        '_params.__dict__["id_inputs"]=_compat.adapt_inputs\n'
        'exec(compile(' + repr(params_source) + ',"<trusted-fixture-params>","exec"),_params.__dict__)\n'
        'def make_input_builder(raw):\n'
        '    baseline=_control.make_input_builder(raw)\n'
        '    return lambda work,nonce,identity: _params.adapt_inputs(baseline(work,nonce,identity))\n'
        'def build_inputs(*args,**kwargs):\n'
        '    return _params.adapt_inputs(_control.build_inputs(*args,**kwargs))\n'
    )
    if len(result.encode('utf-8')) > 16384:
        raise ValueError('Composed builder exceeds guest source limit')
    compile(result, '<trusted-params-control-builder>', 'exec')
    return result

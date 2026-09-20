"""Managed entry for the fixed inert prepared-candidate trial."""
import json
import sys

from mcp_probe_entry import interruption_cleanup
import prepared_candidate_trial_runner as runner
import prepared_candidate_trial_state as state
import prepared_trial_project as project
import prepared_candidate_trial_seed as seed


def main(arguments):
    if arguments not in (['--prepare'], ['--inspect'], ['--inspect-guest'],
                         ['--diagnose-seed'],
                         ['--seed'], ['--preflight'], ['--once']):
        raise ValueError('Fixed prepared-candidate trial action required')
    with interruption_cleanup():
        if arguments == ['--prepare']:
            result = {'state': state.prepare(), 'project': project.inspect()}
        elif arguments == ['--inspect']:
            result = {'state': state.inspect(runtime=True), 'project': project.inspect()}
        elif arguments == ['--inspect-guest']:
            result = seed.inspect_existing()
        elif arguments == ['--diagnose-seed']:
            result = seed.diagnose_seed_v3()
        elif arguments == ['--seed']:
            result = seed.seed()
        elif arguments == ['--preflight']:
            result = runner.preflight()
        else:
            result = runner.run()
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])

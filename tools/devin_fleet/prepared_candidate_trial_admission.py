"""Fixed candidate admission for the inert prepared-candidate trial only."""

from candidate_turn_admission import make_admission as _make_admission
from prepared_candidate_trial_state import check_runtime_registration


def make_admission(registration, binding):
    return _make_admission(registration, binding,
        registration_check=check_runtime_registration)

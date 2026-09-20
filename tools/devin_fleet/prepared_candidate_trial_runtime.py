"""Trial-only runtime view at the candidate-bound guest repository root."""
from contextlib import contextmanager

from sandbox_repository import GuestRepository
from sandbox_runtime import SandboxRuntime
import prepared_candidate_trial_state as state


class PreparedCandidateTrialRuntime(SandboxRuntime):
    def __init__(self, registration, root, *, capacity=1):
        super().__init__(registration, root, capacity=capacity)
        self.trial_guest_root=state.trial_guest_root()

    @contextmanager
    def role(self, role):
        if role!='machine':
            raise ValueError('Fixed trial runtime admits only machine')
        with super().role(role) as existing:
            yield GuestRepository(existing.controller,self.trial_guest_root,
                existing.log_dir,timeout=existing.timeout,
                max_output_bytes=existing.max_output_bytes,
                external_stop=existing.external_stop)

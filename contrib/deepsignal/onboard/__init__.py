"""DeepSignal sensor onboarding engine."""

from .fingerprint import Candidate, identify
from .propose import propose, proposal_yaml
from .trial import TrialResult, run_trial

__all__ = ["Candidate", "TrialResult", "identify", "propose", "proposal_yaml", "run_trial"]

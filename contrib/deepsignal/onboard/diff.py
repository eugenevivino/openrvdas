"""Preview and safely write onboarding proposals."""
import difflib
from pathlib import Path

import yaml

from .propose import proposal_yaml


def proposal_diff(cruise_file, proposal):
    """Return an additions-only unified diff for appending proposal config."""
    original = Path(cruise_file).read_text(encoding="utf-8")
    addition = "\n# DeepSignal onboarding proposal\n" + yaml.safe_dump(
        proposal, sort_keys=False
    )
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True), (original + addition).splitlines(keepends=True),
        fromfile=str(cruise_file), tofile=str(cruise_file) + " + proposal",
    ))


def write_proposal(path, proposal, capture):
    """Write only to a new file, atomically refusing an existing path."""
    path = Path(path)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(proposal_yaml(proposal, capture))
    except FileExistsError:
        raise FileExistsError(
            f"write path: saw existing file {path}; expected a new path; "
            "example: onboard-proposal.yaml"
        ) from None

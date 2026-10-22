"""
A stand-in for qq, for tests that run xtcscope in a subprocess.

It serves the one job described by the JSON file in $FAKE_QQ_JOB, with the
keys of `xtcscope.job.Job` plus `shared` (what `is_shared` answers).
"""

import json
import os
from pathlib import Path


def fake_job() -> dict:
    """The job description from $FAKE_QQ_JOB."""
    return json.loads(Path(os.environ["FAKE_QQ_JOB"]).read_text())

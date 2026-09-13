"""Resume a prepared single-task native SWE-MM smoke, including official scoring."""

import argparse
import time
from pathlib import Path

from benchmarks.swe_mm.cluster_runner import run_and_score
from mm_harness.core.artifacts import read_json
from mm_harness.evolution.minibatch import Pending

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--attempt", type=Path, required=True)
parser.add_argument("--wait", action="store_true")
args = parser.parse_args()
request = read_json(args.attempt / "actor-request.json")
while True:
    try:
        result = run_and_score(request["identity"], Path(request["source"]), args.attempt)
        print({key: result[key] for key in ("task_id", "harness_id", "status", "score", "cost")})
        break
    except Pending as exc:
        print(str(exc), flush=True)
        if not args.wait:
            break
        time.sleep(30)

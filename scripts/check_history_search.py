"""Build a reviewable three-round fixture; no models, benchmark services or GPUs."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from experiments.fixtures.history_search import make_fixture
from mm_harness.core.artifacts import write_json
from mm_harness.evolution.search import run_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--mode", choices=["text", "multimodal"], default="multimodal")
    args = parser.parse_args()
    if Path(args.name).name != args.name:
        raise ValueError("Use a single-component run name")
    directory = Path(__file__).resolve().parents[1] / "runs" / args.name
    directory.mkdir()
    kwargs, calls, b_calls, _, _, fake_claude = make_fixture(directory, args.mode)
    with patch("mm_harness.evolution.source_proposer.run_claude", fake_claude):
        # Exercise continuation as well as the complete loop.
        run_search(**kwargs, round_limit=1)
        result = run_search(**kwargs)
        run_search(**kwargs)
    summary = {
        "kind": "deterministic_fixture_not_model_or_benchmark_rollout",
        "mode": args.mode,
        "status": result["status"],
        "round_statuses": [r["status"] for r in result["rounds"]],
        "fixture_rollouts": len(calls),
        "scripted_proposals": len(b_calls),
        "selected": result["selected"],
        "history": str(directory / "search/history.md"),
        "real_model_calls": 0,
    }
    write_json(directory / "fixture-result.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

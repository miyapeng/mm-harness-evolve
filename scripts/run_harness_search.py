"""Run/resume the source-harness search using an explicit benchmark execution/scoring worker."""

import argparse
import importlib
import inspect
import json
import time
from pathlib import Path

from mm_harness.core.artifacts import digest, file_digest, read_json
from mm_harness.evolution.minibatch import Pending
from mm_harness.evolution.mutation_policy import resolve_policy
from mm_harness.evolution.search import run_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiment",
        type=Path,
        required=True,
        help="Prepared experiment directory containing experiment.json and versions/H0",
    )
    parser.add_argument(
        "--runner",
        required=True,
        help="module:function; callable(identity, frozen_source_path, attempt_dir)",
    )
    parser.add_argument("--base-url", required=True, help="Fixed model's compatible API endpoint")
    parser.add_argument(
        "--rounds", type=int, default=1, help="Additional rounds in this invocation"
    )
    parser.add_argument(
        "--wait-pending", action="store_true", help="Resume queued workers automatically"
    )
    parser.add_argument("--poll-seconds", type=float, default=30)
    args = parser.parse_args()
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be at least 1")
    root = Path(__file__).resolve().parents[1]
    experiment = read_json(args.experiment / "experiment.json")
    config, roles = experiment["config"], experiment["roles"]
    if resolve_policy(root, config) != experiment["mutation_policy"]:
        raise ValueError("Mutation contract changed since preparation; prepare a new experiment")
    live_roles = read_json(root / config["model_roles"])
    comparable = json.loads(json.dumps(roles))
    comparable["evolver"].pop("system_prompt", None)
    if live_roles != comparable:
        raise ValueError("Role settings changed since preparation; prepare a new experiment")
    module, name = args.runner.split(":", 1)
    runner = getattr(importlib.import_module(module), name)
    search_path = args.experiment / "search/search.json"
    previous = len(read_json(search_path)["rounds"]) if search_path.exists() else 0
    target_rounds = min(config["max_rounds"], previous + args.rounds)
    run_arguments = dict(
        root=root,
        directory=args.experiment / "search",
        config=config,
        split=experiment["split"],
        h0=args.experiment / "versions/H0",
        role=roles["evolver"],
        base_url=args.base_url,
        protocol_id=digest(
            {
                "evaluator": experiment["evaluator_lock"],
                "config": config,
                "runner": args.runner,
                "runner_sha256": file_digest(Path(inspect.getfile(runner))),
            }
        ),
        model_id=roles["actor"]["model"],
        runner=runner,
        round_limit=args.rounds,
    )
    while True:
        completed = len(read_json(search_path)["rounds"]) if search_path.exists() else 0
        run_arguments["round_limit"] = max(1, target_rounds - completed)
        try:
            result = run_search(**run_arguments)
            break
        except Pending as exc:
            if not args.wait_pending:
                raise
            print(str(exc), flush=True)
            time.sleep(args.poll_seconds)
    print(
        json.dumps(
            {
                "status": result["status"],
                "completed_rounds": len(result["rounds"]),
                "selected": result["selected"],
                "history": str(args.experiment / "search/history.md"),
            }
        )
    )


if __name__ == "__main__":
    main()

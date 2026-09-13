"""Open held-out test tasks only after a completed run has frozen a selected candidate."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    frozen = json.loads((run / "frozen-selection.json").read_text())
    config = frozen["experiment"]
    code_root = Path(config["code_root"])
    sys.path[:0] = [
        str(code_root / "src"),
        str(code_root),
        str(run.parent.parent / "third_party/AutoSaddler-main/src"),
    ]
    from mm_harness.core.artifacts import digest, read_json, tree_manifest, write_json
    from mm_harness.core.schema import Task
    from mm_harness.core.store import RunStore
    from mm_harness.evolution.autosaddler import adapter_for
    from mm_harness.runtimes.model import ChatModel

    if {
        "src": tree_manifest(code_root / "src"),
        "benchmarks": tree_manifest(code_root / "benchmarks"),
    } != config["code_fingerprint"]:
        raise ValueError("Frozen execution source changed")
    version = frozen["selected_candidate_id"]
    files = read_json(run / "candidates" / version.removeprefix("sha256:") / "candidate.json")
    if "sha256:" + digest(files) != version:
        raise ValueError("Frozen candidate identity changed")
    guard = RunStore(run / "test-controller")
    try:
        guard.initialize({"selected": version, "experiment": frozen["config_sha256"]})
        role = config["roles"]["executor"]
        adapter = adapter_for(config, ChatModel(config["providers"][role["provider"]], role))
        outcomes = []
        for raw in config["tasks"]:
            if raw["split"] != "test":
                continue
            task = Task(**raw)
            for repetition in range(config["repetitions"]):
                directory = run / "post_optimization/test" / digest([task.task_id, repetition])[:16]
                if (directory / "outcome.json").exists():
                    outcome = read_json(directory / "outcome.json")
                    if (
                        outcome["task_id"],
                        outcome["harness_id"],
                        outcome["repetition"],
                        outcome["split"],
                        outcome["evaluator_id"],
                    ) != (
                        task.task_id,
                        version,
                        repetition,
                        "test",
                        adapter.fingerprint,
                    ):
                        raise ValueError("Test cache identity mismatch")
                else:
                    attempt = directory / f"attempt-{len(list(directory.glob('attempt-*'))) + 1}"
                    source = attempt / "harness"
                    source.mkdir(parents=True)
                    for name, value in files.items():
                        (source / name).write_text(value)
                    outcome = adapter.run(task, source, version, repetition, attempt).to_dict()
                    write_json(directory / "outcome.json", outcome)
                outcomes.append(outcome)
                print(task.task_id, outcome["status"], outcome["score"], flush=True)
        valid = [
            o
            for o in outcomes
            if o["status"] in ("success", "task_failure") and o["score"] is not None
        ]
        result = {
            "selected_candidate_id": version,
            "test_opened_after_freeze": True,
            "outcomes": outcomes,
            "valid": len(valid),
            "requested": len(outcomes),
            "mean_score": sum(o["score"] for o in valid) / len(valid) if valid else None,
            "generalization_claim": False,
            "protocol": config["protocol"],
        }
        write_json(run / "test-result.json", result)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in ["outcomes", "protocol"]}, indent=2
            )
        )
    finally:
        guard.close()


if __name__ == "__main__":
    main()

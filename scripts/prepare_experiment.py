"""Freeze any wired benchmark. Preparation is local and does not call a model."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from mm_harness.core.artifacts import read_json, tree_manifest, write_json
from mm_harness.core.benchmarks import NAMES, check_configuration, profile
from mm_harness.core.schema import Task, validate_splits
from mm_harness.runtimes.model import assert_same_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", choices=NAMES, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--adapter-config", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument(
        "--policy", type=Path, help="Evolution policy; defaults to configs/evolution/default.json"
    )
    parser.add_argument("--h0", type=Path)
    parser.add_argument("--mode", choices=["text", "multimodal"], default="multimodal")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    if args.rounds < 1 or args.repetitions < 1:
        parser.error("rounds and repetitions must be positive")
    root = Path(__file__).resolve().parents[1]
    target = root / "configs" / f"{args.name}.json"
    frozen = root / "experiments/frozen" / args.name
    if target.exists() or frozen.exists():
        raise FileExistsError("Use a new experiment name")
    models, wiring = read_json(args.models), read_json(args.adapter_config)
    assert_same_model(models)
    if wiring["benchmark"] != args.benchmark:
        raise ValueError("Adapter/benchmark mismatch")
    report = check_configuration(wiring)
    if not report["configured"]:
        raise ValueError(f"Finish benchmark wiring first: {report['missing']}")
    tasks = [Task(**value) for value in read_json(args.tasks)]
    validate_splits(tasks)
    if any(t.benchmark != args.benchmark for t in tasks):
        raise ValueError("Task/benchmark mismatch")
    if {t.split for t in tasks} != {"exploration", "validation", "test"}:
        raise ValueError("Provide nonempty exploration, validation and test splits")
    for name in ("src", "benchmarks"):
        shutil.copytree(
            root / name, frozen / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    h0 = args.h0 or root / "benchmarks" / args.benchmark / "h0"
    (frozen / "h0").mkdir()
    for name in ("harness.py", "prompt.txt"):
        shutil.copy2(h0 / name, frozen / "h0" / name)
    policy = read_json(args.policy or root / "configs/evolution/default.json")
    if policy["evolver_runtime"] != "bounded_multimodal_http":
        raise ValueError(
            "Only the bounded HTTP evolver is currently wired; SDK has a separate probe"
        )
    config = {
        **models,
        "benchmark": args.benchmark,
        "adapter": wiring["adapter"],
        "tasks": [t.__dict__ for t in tasks],
        "h0": str(frozen / "h0"),
        "h0_fingerprint": tree_manifest(frozen / "h0"),
        "h0_files": {
            name: (frozen / "h0" / name).read_text() for name in ("harness.py", "prompt.txt")
        },
        "runtimes": {
            "evolver": policy["evolver_runtime"],
            "executor": wiring["adapter"].get("transport", "native_python"),
        },
        "protocol": {
            **profile(args.benchmark)["protocol"],
            "split_source": str(args.tasks.resolve()),
            "h0_source": str(h0.resolve()),
            "generalization_claim": False,
        },
        "code_root": str(frozen),
        "code_fingerprint": {name: tree_manifest(frozen / name) for name in ("src", "benchmarks")},
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "upstream": read_json(root / "third_party/lock.json"),
        "repetitions": args.repetitions,
        "evidence_mode": args.mode,
        "max_images": policy["max_images"],
        "optimization_target": policy["optimization_target"],
        "selection": policy["selection"],
    }
    write_json(target, config)
    role = config["roles"]["evolver"]
    train_count = sum(t.split == "exploration" for t in tasks)
    validation_count = sum(t.split == "validation" for t in tasks)
    max_rollouts = (
        validation_count + args.rounds * (2 * train_count + validation_count)
    ) * args.repetitions
    control = {
        "schema_version": "autosaddler/v2",
        "scenario": {"type": "mm_harness", "settings": {"experiment": target.name}},
        "optimization": {
            "task_selection": {"type": "fixed", "batch_size": train_count},
            "acceptance": {"type": "validation_eligible"},
            "development": {"type": "full_on_accept"},
            "ranking": {"type": "mm_cost_regression"},
            "budget": {"max_iterations": args.rounds, "max_rollouts": max_rollouts},
            "session_retries": 0,
            "diagnosis_patch_timeout_seconds": role["timeout_seconds"],
        },
        "provider": {
            "type": "mm_http",
            "capabilities": ["read_workspace", "edit_workspace", "network"],
            "settings": {
                "provider": config["providers"][role["provider"]],
                "role": role,
                "seed": policy["seed"],
            },
        },
        "storage": {"type": "local", "run_root": "../runs"},
    }
    output = target.with_suffix(".autosaddler.json")
    write_json(output, control)
    print(json.dumps({"config": str(output), "environment_tested": False}, indent=2))


if __name__ == "__main__":
    main()

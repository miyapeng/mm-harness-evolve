"""Freeze a fresh pilot and validate its official SWE-agent loading path."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from mm_harness.core.artifacts import digest, file_digest, read_json, tree_manifest, write_json
from mm_harness.evolution.minibatch import plan_batches
from mm_harness.evolution.mutation_policy import resolve_policy
from mm_harness.evolution.source_versions import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/evolution/swe-mm-mechanism-pilot.json")
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if Path(args.name).name != args.name:
        raise ValueError("Experiment name must be a single path component")
    output = root / "runs" / args.name
    output.mkdir()  # A fresh experiment has a new identity; never overwrite a previous sample.
    config = read_json(root / args.config)
    roles = read_json(root / config["model_roles"])
    if (
        roles["actor"]["model"] != roles["evolver"]["model"]
        or roles["actor"]["model"] != roles["provider"]["model"]
    ):
        raise ValueError("Main experiments require A=B=the served model")
    prompt = root / roles["evolver"]["system_prompt_file"]
    roles["evolver"]["system_prompt"] = prompt.read_text()
    split = read_json(root / config["split"])
    first_batch = plan_batches(config=config, split=split, round_index=0)
    lock = read_json(root / "third_party/lock.json")
    h0 = snapshot(root / lock["upstreams"]["SWE-agent"]["path"], output / "versions/H0")
    experiment = {
        "name": args.name,
        "config": config,
        "mutation_policy": resolve_policy(root, config),
        "roles": roles,
        "split": split,
        "first_batch_preview": first_batch,
        "h0": h0["id"],
        "source_lock": lock["upstreams"]["SWE-agent"],
        "evaluator_lock": lock["upstreams"]["SWE-bench"],
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "working_tree_diff_sha256": digest(
            subprocess.check_output(["git", "diff", "HEAD"], cwd=root, text=True)
        ),
        "prompt_sha256": file_digest(prompt),
        "runtime_files": {
            str(p.relative_to(root)): file_digest(p)
            for base in (root / "src", root / "scripts", root / "benchmarks/swe_mm")
            for name in tree_manifest(base)
            if (p := base / name).suffix in {".py", ".sh", ".json", ".yaml", ".txt"}
        },
        "stage": "source_frozen_container_and_model_pending",
    }
    write_json(output / "experiment.json", experiment)
    rows = [
        json.loads(line)
        for line in (root / "data/swe_mm/dev/agent_visible/sweagent-instances.jsonl")
        .read_text()
        .splitlines()
    ]
    instance = next(r for r in rows if r["instance_id"] == first_batch["exploration"][0])
    request = {
        "source": str(output / "versions/H0/source"),
        "instance": instance,
        "role": roles["actor"],
        "base_url": "http://127.0.0.1:1/v1",
        "output": str(output / "native-check-no-rollout"),
        "identity": {"task_id": instance["instance_id"], "harness_id": h0["id"]},
    }
    write_json(output / "native-check.json", request)
    result = subprocess.run(
        [
            str(root / ".venv-swe-agent/bin/python"),
            str(root / "benchmarks/swe_mm/native_actor.py"),
            "--request",
            str(output / "native-check.json"),
            "--check",
        ],
        cwd=output / "versions/H0/source",
        text=True,
        capture_output=True,
    )
    write_json(
        output / "native-check-result.json",
        {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "rollout_executed": False,
        },
    )
    if result.returncode:
        raise RuntimeError(f"Native config check failed; inspect {output}")
    print(
        json.dumps(
            {
                "experiment": str(output),
                "h0": h0["id"],
                "native_configuration_valid": True,
                "rollout_executed": False,
            }
        )
    )


if __name__ == "__main__":
    main()

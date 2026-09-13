"""Print (or explicitly execute) the official multimodal H0 batch command.

This is an upstream baseline launcher, not a completed mm_harness execute/score worker.
It does not replace the benchmark's loop, system prompt, media policy or grader.
"""

import argparse
import json
import subprocess
from pathlib import Path


def batch_command(
    upstream: Path,
    config: Path,
    output: Path,
    *,
    tasks_dir=None,
    executable="claw-eval",
    trials=3,
    parallel=1,
    task_id=None,
):
    if trials < 1 or parallel < 1:
        raise ValueError("trials and parallel must be positive")
    tasks_dir = Path(tasks_dir) if tasks_dir is not None else upstream / "tasks"
    argv = [
        executable,
        "batch",
        "--config",
        str(config.resolve()),
        "--tasks-dir",
        str(tasks_dir.resolve()),
        "--tag",
        "multimodal",
        "--sandbox",
        "--trials",
        str(trials),
        "--parallel",
        str(parallel),
        "--trace-dir",
        str(output.resolve()),
    ]
    if task_id:
        # Native --filter uses substring matching; ensure a one-task request stays one task.
        matches = [p for p in tasks_dir.iterdir() if task_id in p.name and p.is_dir()]
        if len(matches) != 1 or matches[0].name != task_id:
            raise ValueError("task-id must select exactly one official task directory")
        import yaml

        task = yaml.safe_load((matches[0] / "task.yaml").read_text())
        if "multimodal" not in task.get("tags", []):
            raise ValueError("Selected task is outside the official multimodal subset")
        argv.extend(["--filter", task_id])
    return argv


def main():
    root = Path(__file__).resolve().parents[3]
    profile = json.loads(Path(__file__).with_name("profile.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", type=Path, default=root / profile["upstream"]["path"])
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=root / "benchmarks/claw_eval_mm/data/tasks",
        help="materialized benchmark-local task tree",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Defaults to the official config_multimodal.yaml; override model A here",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable", default=str(root / ".venv-claw/bin/claw-eval"))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--task-id", help="Select exactly one official multimodal task")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Start the official baseline; otherwise only print its argv",
    )
    args = parser.parse_args()
    config = args.config or args.upstream_root / "config_multimodal.yaml"
    command = batch_command(
        args.upstream_root,
        config,
        args.output,
        tasks_dir=args.tasks_dir,
        executable=args.executable,
        trials=args.trials,
        parallel=args.parallel,
        task_id=args.task_id,
    )
    print(
        json.dumps(
            {"command": command, "executed": args.execute, "scope": "official_multimodal_h0"},
            indent=2,
        ),
        flush=True,
    )
    if args.execute:
        subprocess.run(command, cwd=args.upstream_root, check=True)


if __name__ == "__main__":
    main()

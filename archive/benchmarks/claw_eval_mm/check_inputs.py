"""Validate official multimodal task definitions and declared local fixture availability."""

import argparse
import json
from pathlib import Path

from claw_eval.config import load_config
from claw_eval.models.task import TaskDefinition
from claw_eval.runner.media_loader import collect_media_references


def main():
    root = Path(__file__).resolve().parents[3]
    lock = json.loads((root / "third_party/lock.json").read_text())
    spec = lock["upstreams"]["Claw-Eval"]
    dataset_source = json.loads((root / "benchmarks/claw_eval_mm/data/SOURCE.json").read_text())
    source = root / spec["path"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=source / "tasks",
        help="task tree to audit; use benchmark data/tasks after materialization",
    )
    args = parser.parse_args()
    resolved_tasks_dir = args.tasks_dir.resolve()
    try:
        reported_tasks_dir = str(resolved_tasks_dir.relative_to(root))
    except ValueError:
        reported_tasks_dir = str(resolved_tasks_dir)
    cfg = load_config(source / "config_multimodal.yaml")
    missing, complete, initial_media = [], [], []
    for path in sorted(args.tasks_dir.glob("*/task.yaml")):
        task = TaskDefinition.from_yaml(path)
        if "multimodal" not in task.tags:
            continue
        fields = {
            "sandbox_files": task.sandbox_files or task.environment.fixtures,
            "sandbox_grader_files": task.sandbox_grader_files,
            "local_grader_files": task.local_grader_files,
        }
        absent = [
            {"field": field, "path": ref}
            for field, refs in fields.items()
            for ref in refs
            if not (path.parent / ref).exists() and not (args.tasks_dir.parent / ref).exists()
        ]
        if absent:
            missing.append({"task_id": task.task_id, "missing": absent})
        else:
            complete.append(task.task_id)
        if collect_media_references(task.prompt.text, task.prompt.attachments):
            initial_media.append(task.task_id)
    report = {
        "source_commit": spec["commit"],
        "dataset_revision": dataset_source["revision"],
        "tasks_dir": reported_tasks_dir,
        "scope": "official task validation and declared sandbox/fixture/grader files; dynamic service media and container execution not tested",
        "multimodal_tasks": len(complete) + len(missing),
        "declared_files_present_tasks": len(complete),
        "declared_files_present_ids": complete,
        "missing": missing,
        "official_config_input_modalities": cfg.model.input_modalities,
        "tasks_with_initial_media_references": initial_media,
        "modality_note": "initial prompt media is gated by input_modalities; tool-result image injection is a separate path",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "tasks_validated": report["multimodal_tasks"],
                "declared_files_present_tasks": len(complete),
                "missing_tasks": len(missing),
                "report": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()

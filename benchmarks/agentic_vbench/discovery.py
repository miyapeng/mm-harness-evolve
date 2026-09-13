"""Static inventory only: do not import Harbor or execute task/environment scripts."""

import tomllib
from pathlib import Path

from mm_harness.core.artifacts import file_digest
from mm_harness.core.schema import Task

OFFICIAL_FAMILIES = ("repair", "assembly", "sequencing", "repurpose")


def discover(source: Path, *, include_extra_families=False):
    tasks = []
    for spec in sorted((source / "tasks").glob("*/*/task.toml")):
        family = spec.parent.parent.name.removeprefix("agentic_vbench_")
        if family not in OFFICIAL_FAMILIES and not include_extra_families:
            continue
        tomllib.loads(spec.read_text())  # Syntax check only; no upstream code execution.
        instruction = spec.parent / "steps/solve/instruction.md"
        if not instruction.is_file():
            continue
        tasks.append(
            Task(
                task_id=f"{family}/{spec.parent.name}",
                benchmark="agentic_vbench",
                split="unassigned",
                group=family,
                payload={
                    "agent_input": {"instruction": instruction.read_text()},
                    "instruction_sha256": file_digest(instruction),
                    "upstream_task_ref": str(spec.parent.relative_to(source)),
                    "environment_media_export": "pending allowlisted per-task build review",
                    "upstream_split": "public_evaluation",
                    "development_approved": False,
                },
            )
        )
    return tasks

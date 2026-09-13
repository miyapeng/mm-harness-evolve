from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Split = Literal["exploration", "validation", "test"]
Status = Literal[
    "success", "task_failure", "environment_error", "model_error", "timeout", "unscored"
]


@dataclass(frozen=True)
class Task:
    task_id: str
    benchmark: str
    split: Split
    group: str
    payload: dict


@dataclass
class Cost:
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    visual_observations: int = 0
    wall_seconds: float = 0.0
    dollars: float | None = None


@dataclass
class Outcome:
    task_id: str
    harness_id: str
    split: Split
    repetition: int
    status: Status
    score: float | None
    metrics: dict
    cost: Cost
    evaluator_id: str
    rollout: str
    error: str | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, "cost": Cost(**value["cost"])})


def validate_splits(tasks: list[Task]) -> None:
    ids, groups = set(), {}
    for task in tasks:
        if task.split not in ("exploration", "validation", "test"):
            raise ValueError(f"Unknown split: {task.split}")
        key = task.benchmark, task.task_id
        if key in ids:
            raise ValueError(f"Duplicate task: {key}")
        ids.add(key)
        group = task.benchmark, task.group
        if not task.group or groups.get(group, task.split) != task.split:
            raise ValueError(f"Group crosses splits: {group}")
        groups[group] = task.split

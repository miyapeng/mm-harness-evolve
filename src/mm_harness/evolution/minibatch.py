"""Small, resumable single-candidate search; no model-based acceptance judge.

The runner owns task environments and durable attempt records. A pending remote
job raises Pending, leaving completed stages available to the next invocation.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Callable

from mm_harness.core.artifacts import digest, read_json, write_json


class Pending(RuntimeError):
    """An external service/job has not completed; resume without resampling."""


def plan_batches(*, config: dict, split: dict, round_index: int) -> dict:
    """Shuffle each pool per epoch and visit without replacement; indices start at zero.

    A final short batch completes an epoch instead of repeating tasks to fill it.
    E and V have independent schedules; scores never influence V selection.
    """
    if type(round_index) is not int or round_index < 0:
        raise ValueError("round_index must be a nonnegative integer")
    if split.get("upstream_split") not in {"train", "dev", "validation"}:
        raise ValueError("Evolution requires an official development split")
    pools = {key: split[key] for key in ("exploration", "validation")}
    reserved = set(split.get("test", [])) | set(split.get("test_frozen_only", []))
    for pool in pools.values():
        if not pool or len(set(pool)) != len(pool) or set(pool) & reserved:
            raise ValueError("Pools must be nonempty, unique and exclude reserved test tasks")
    if set(pools["exploration"]) & set(pools["validation"]):
        raise ValueError("E and V must be disjoint")
    seed = config["task_sampling_seed"]
    plan = {"round_index": round_index, "seed": seed, "schedule": "shuffled_epochs"}
    for name, size_key in (
        ("exploration", "evolution_batch_size"),
        ("validation", "validation_batch_size"),
    ):
        size = config[size_key]
        if type(size) is not int or size < 1:
            raise ValueError(f"{size_key} must be a positive integer")
        pool = sorted(pools[name])
        batches_per_epoch = math.ceil(len(pool) / size)
        epoch, batch_index = divmod(round_index, batches_per_epoch)
        random.Random(f"{seed}:{name}:{epoch}").shuffle(pool)
        plan[name] = pool[batch_index * size : (batch_index + 1) * size]
        plan[f"{name}_epoch"] = epoch
    return plan


def run_configured_round(
    directory: Path,
    *,
    config: dict,
    split: dict,
    round_index: int,
    parent: str,
    protocol_id: str,
    model_id: str,
    runner: Callable,
    proposer: Callable,
) -> dict:
    """Configuration-driven entry to the existing single-candidate pilot.

    Both sizes control actual runner calls. This does not implement multi-branch
    search or the optional statistical gate; real SWE workers remain separate.
    """
    if config.get("candidates_per_round") != 1 or config.get("rollouts_per_task") != 1:
        raise ValueError("This pilot supports one candidate and one rollout per task")
    for key, expected in (
        ("batch_gate", "mean_candidate_strictly_greater_than_parent"),
        ("dev_gate", "mean_candidate_greater_or_equal_to_parent"),
    ):
        if key in config and config[key] != expected:
            raise ValueError(f"Unsupported {key}; this controller must match the configured gate")
    spec = {
        "config": config,
        "split": split,
        "round_index": round_index,
        "parent": parent,
        "protocol_id": protocol_id,
        "model_id": model_id,
    }
    path = directory / "batch-plan.json"
    if path.exists():
        saved = read_json(path)
        if saved["spec"] != spec:
            raise ValueError("Resume sampling inputs differ; use a new round directory")
        plan = saved["plan"]
        if plan != plan_batches(config=config, split=split, round_index=round_index):
            raise ValueError("Saved batch plan does not match frozen sampling inputs")
    else:
        plan = plan_batches(config=config, split=split, round_index=round_index)
        write_json(path, {"spec": spec, "plan": plan})
    return run_round(
        directory,
        parent=parent,
        batch=plan["exploration"],
        dev=plan["validation"],
        protocol_id=protocol_id,
        model_id=model_id,
        runner=runner,
        proposer=proposer,
        max_parallel_rollouts=config.get("max_parallel_rollouts", 1),
    )


def compare(parent: list[dict], candidate: list[dict], *, strict: bool) -> dict:
    def indexed(rows):
        keys = [
            (r["task_id"], r["sample"], r["split"], r["protocol_id"], r["model_id"]) for r in rows
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate task/sample in comparison")
        return dict(zip(keys, rows, strict=True))

    p, c = indexed(parent), indexed(candidate)
    if not p or p.keys() != c.keys():
        raise ValueError("Comparison requires identical tasks, samples, model and scoring protocol")
    if any(
        r["status"] not in {"success", "task_failure"}
        or r.get("score") is None
        or not math.isfinite(r["score"])
        for r in [*parent, *candidate]
    ):
        return {
            "passed": False,
            "status": "inconclusive",
            "reason": "incomplete_or_environment_error",
        }
    grouped = defaultdict(list)
    parent_grouped, child_grouped = defaultdict(list), defaultdict(list)
    for k in p:
        grouped[k[0]].append(c[k]["score"] - p[k]["score"])
        parent_grouped[k[0]].append(p[k]["score"])
        child_grouped[k[0]].append(c[k]["score"])
    gains = {task: sum(grouped[task]) / len(grouped[task]) for task in sorted(grouped)}
    delta = sum(gains.values()) / len(gains)
    return {
        "passed": delta > 0 if strict else delta >= 0,
        "status": "compared",
        "gain": delta,
        "per_task_gain": gains,
        "parent_mean": sum(sum(v) / len(v) for v in parent_grouped.values()) / len(gains),
        "candidate_mean": sum(sum(v) / len(v) for v in child_grouped.values()) / len(gains),
        "samples_per_task": {task: len(values) for task, values in grouped.items()},
        "regressions": [task for task, gain in gains.items() if gain < 0],
        "improvements": [task for task, gain in gains.items() if gain > 0],
    }


def run_round(
    directory: Path,
    *,
    parent: str,
    batch: list[str],
    dev: list[str],
    protocol_id: str,
    model_id: str,
    runner: Callable,
    proposer: Callable,
    max_parallel_rollouts: int = 1,
) -> dict:
    if type(max_parallel_rollouts) is not int or max_parallel_rollouts < 1:
        raise ValueError("max_parallel_rollouts must be a positive integer")
    if not batch or not dev or set(batch) & set(dev):
        raise ValueError("Nonempty, disjoint exploration and dev tasks required")
    if len(set(batch)) != len(batch) or len(set(dev)) != len(dev):
        raise ValueError("Duplicate task in split")
    spec = {
        "parent": parent,
        "batch": batch,
        "dev": dev,
        "protocol_id": protocol_id,
        "model_id": model_id,
    }
    state_path = directory / "round.json"
    if state_path.exists():
        state = read_json(state_path)
        if state["spec"] != spec:
            raise ValueError("Resume inputs differ; use a new round for new sampling")
    else:
        state = {"spec": spec, "status": "parent_ready", "attempts": {}}
        write_json(state_path, state)
    if state["status"] in {
        "accepted",
        "batch_rejected",
        "dev_rejected",
        "no_change",
        "invalid",
        "inconclusive",
    }:
        return state

    def collect(version, tasks, split):
        results = []
        pending = []
        for task in tasks:
            identity = {
                "task_id": task,
                "sample": 0,
                "split": split,
                "harness_id": version,
                "protocol_id": protocol_id,
                "model_id": model_id,
            }
            key = digest(identity)
            if key not in state["attempts"]:
                try:
                    result = runner(identity, directory / "attempts" / key)
                except Pending as exc:
                    pending.append(str(exc))
                    if len(pending) >= max_parallel_rollouts:
                        break
                    continue
                if any(result.get(k) != v for k, v in identity.items()):
                    raise ValueError("Runner returned a result for the wrong task/version/protocol")
                state["attempts"][key] = result
                write_json(state_path, state)
            if any(state["attempts"][key].get(k) != v for k, v in identity.items()):
                raise ValueError("Cached result does not match the requested task/version/protocol")
            results.append(state["attempts"][key])
        if pending:
            raise Pending("; ".join(pending))
        return results

    parent_batch = collect(parent, batch, "exploration")
    if any(r["status"] not in {"success", "task_failure"} for r in parent_batch):
        state.update(status="inconclusive", reason="parent_environment_error", selected=parent)
        write_json(state_path, state)
        return state
    if "proposal" not in state:
        # Only exploration records are passed to the proposer. It never receives dev trajectories.
        state["proposal"] = proposer(parent, parent_batch, directory / "proposal")
        state["status"] = "proposal_ready"
        write_json(state_path, state)
    proposal = state["proposal"]
    if proposal["status"] in {"no_change", "invalid"}:
        state["status"] = proposal["status"]
    else:
        child = proposal["harness_id"]
        child_batch = collect(child, batch, "exploration")
        if proposal.get("mechanism_patch"):
            import json

            from mm_harness.core.mechanisms import MechanismPatch
            from mm_harness.core.observability import summarize_mechanisms

            mechanism = MechanismPatch.from_dict(read_json(Path(proposal["mechanism_patch"])))
            summaries = []
            for result in child_batch:
                events_path = (
                    Path(result["rollout"]) / "events.jsonl" if result.get("rollout") else None
                )
                events = (
                    [
                        json.loads(line)
                        for line in events_path.read_text().splitlines()
                        if line.strip()
                    ]
                    if events_path and events_path.is_file()
                    else []
                )
                summaries.append(
                    {
                        "task_id": result["task_id"],
                        "harness_id": child,
                        **summarize_mechanisms(events, proposal=mechanism, implemented=True),
                    }
                )
            write_json(directory / "mechanism-observations.json", summaries)
            state["mechanism_observations"] = str(directory / "mechanism-observations.json")
        state["batch_comparison"] = compare(parent_batch, child_batch, strict=True)
        write_json(state_path, state)
        if state["batch_comparison"]["status"] == "inconclusive":
            state["status"] = "inconclusive"
        elif not state["batch_comparison"]["passed"]:
            state["status"] = "batch_rejected"
        else:
            parent_dev = collect(parent, dev, "validation")
            child_dev = collect(child, dev, "validation")
            state["dev_comparison"] = compare(parent_dev, child_dev, strict=False)
            if state["dev_comparison"]["status"] == "inconclusive":
                state["status"] = "inconclusive"
            else:
                state["status"] = (
                    "accepted" if state["dev_comparison"]["passed"] else "dev_rejected"
                )
    state["selected"] = proposal["harness_id"] if state["status"] == "accepted" else parent
    write_json(state_path, state)
    return state

"""Task-paired validation gate. Not yet wired into the SWE rollout controller.

Average repetitions within each task, then bootstrap tasks with replacement.
The percentile interval is a development signal, not a sequential-testing or
cross-family generalization guarantee. Cost caps are absolute per-rollout means.
"""

from __future__ import annotations

import math
import random

from mm_harness.evolution.minibatch import compare


def validation_gate(
    champion: list[dict],
    candidate: list[dict],
    *,
    champion_id: str,
    candidate_id: str,
    expected_tasks: list[str],
    expected_samples: list[int],
    cost_caps: dict[str, float],
    seed: int,
    resamples: int = 10000,
) -> dict:
    """Rows additionally carry initial_state_id and budget_id for actual pairing.

    Callers must pass the frozen task/sample manifest, not infer it from outputs.
    Non-task failures yield inconclusive; identity mistakes raise rather than
    silently matching incompatible experiments. Missing cost never means zero.
    """
    if len(expected_tasks) < 2 or len(set(expected_tasks)) != len(expected_tasks):
        raise ValueError("At least two unique validation tasks required")
    if not expected_samples or len(set(expected_samples)) != len(expected_samples):
        raise ValueError("Unique nonempty sample manifest required")
    if resamples < 100 or not cost_caps:
        raise ValueError("Specify at least 100 resamples and explicit cost caps")
    if any(not math.isfinite(v) or v < 0 for v in cost_caps.values()):
        raise ValueError("Cost caps must be finite and nonnegative")
    expected = {(task, sample) for task in expected_tasks for sample in expected_samples}
    for rows, version in ((champion, champion_id), (candidate, candidate_id)):
        keys = [(r["task_id"], r["sample"]) for r in rows]
        if set(keys) != expected or len(keys) != len(expected):
            raise ValueError("Results do not match frozen task/sample manifest")
        if any(r["harness_id"] != version or r["split"] != "validation" for r in rows):
            raise ValueError("Wrong validation harness or split")
        for r in rows:
            if not r.get("initial_state_id") or not r.get("budget_id"):
                raise ValueError("Pairing requires initial state and budget identity")
    indexed = {(r["task_id"], r["sample"]): r for r in champion}
    for r in candidate:
        parent = indexed[r["task_id"], r["sample"]]
        if any(r[k] != parent[k] for k in ("initial_state_id", "budget_id")):
            raise ValueError("Initial state or budget differs within a pair")
    report = compare(champion, candidate, strict=True)
    report.pop("passed", None)
    report["accepted"] = False
    if report["status"] == "inconclusive":
        return report

    values = [report["per_task_gain"][task] for task in sorted(expected_tasks)]
    rng = random.Random(seed)
    draws = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(resamples))

    def quantile(q):
        position = (len(draws) - 1) * q
        lo = math.floor(position)
        hi = math.ceil(position)
        return draws[lo] + (draws[hi] - draws[lo]) * (position - lo)

    interval = [quantile(0.025), quantile(0.975)]
    report.update(
        interval=interval,
        bootstrap={
            "unit": "task",
            "method": "percentile",
            "confidence": 0.95,
            "resamples": resamples,
            "seed": seed,
        },
        cost_caps=cost_caps,
        cost_means={},
        inference_scope="development_only_not_adjusted_for_adaptive_selection",
    )
    for role, rows in (("champion", champion), ("candidate", candidate)):
        report["cost_means"][role] = {}
        for metric in cost_caps:
            costs = [r.get("cost", {}).get(metric) for r in rows]
            if any(v is None or not math.isfinite(v) or v < 0 for v in costs):
                report.update(status="inconclusive", reason="missing_or_invalid_cost")
                return report
            report["cost_means"][role][metric] = sum(costs) / len(costs)
    report["cost_passed"] = all(
        report["cost_means"]["candidate"][key] <= limit for key, limit in cost_caps.items()
    )
    report["accepted"] = report["gain"] > 0 and interval[0] > 0 and report["cost_passed"]
    report["reason"] = (
        "positive_interval_within_cost_caps"
        if report["accepted"]
        else "cost_cap_exceeded"
        if not report["cost_passed"]
        else "insufficient_gain_evidence"
    )
    return report

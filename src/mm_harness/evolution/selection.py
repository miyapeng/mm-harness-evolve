from __future__ import annotations

import math

from mm_harness.core.schema import Outcome


def select(
    parent: list[Outcome],
    child: list[Outcome],
    *,
    min_gain=0.0,
    max_regressions=0,
    max_token_ratio=2.0,
    success_threshold=0.8,
) -> dict:
    def key(x):
        return x.task_id, x.repetition, x.split, x.evaluator_id

    p, c = {key(x): x for x in parent}, {key(x): x for x in child}
    if not p or len(p) != len(parent) or len(c) != len(child) or p.keys() != c.keys():
        raise ValueError("Selection needs the exact same unique tasks, repetitions and evaluator")
    if any(x.split != "validation" for x in [*parent, *child]):
        raise ValueError("Selection uses validation tasks only")
    valid = {"success", "task_failure"}
    if any(
        x.status not in valid or x.score is None or not math.isfinite(x.score)
        for x in [*parent, *child]
    ):
        return {"accepted": False, "reason": "incomplete_or_infrastructure_failure", "gain": None}
    gain = sum(c[k].score - p[k].score for k in p) / len(p)
    regressions = [k[0] for k in p if p[k].score >= success_threshold > c[k].score]

    def tokens(xs):
        return sum(x.cost.input_tokens + x.cost.output_tokens for x in xs)

    ratio = tokens(child) / max(1, tokens(parent))
    accepted = gain > min_gain and len(regressions) <= max_regressions and ratio <= max_token_ratio
    return {
        "accepted": accepted,
        "reason": "gain_without_excess_regression_or_cost"
        if accepted
        else "gain_regression_or_cost_gate_failed",
        "gain": gain,
        "regressed_tasks": regressions,
        "token_ratio": ratio,
        "parent_score": sum(x.score for x in parent) / len(parent),
        "candidate_score": sum(x.score for x in child) / len(child),
    }

import pytest

from mm_harness.evolution.minibatch import compare
from mm_harness.evolution.statistical_selection import validation_gate


def rows(version, scores):
    return [
        dict(
            task_id=task,
            sample=sample,
            harness_id=version,
            split="validation",
            protocol_id="p",
            model_id="m",
            budget_id="b",
            initial_state_id=task,
            status="success" if score else "task_failure",
            score=score,
            cost={"input_tokens": 10},
        )
        for task, values in scores.items()
        for sample, score in enumerate(values)
    ]


def gate(p, c, **kwargs):
    return validation_gate(
        p,
        c,
        champion_id="h0",
        candidate_id="h1",
        expected_tasks=["a", "b"],
        expected_samples=[0, 1, 2],
        cost_caps={"input_tokens": 20},
        seed=42,
        resamples=1000,
        **kwargs,
    )


def test_repeats_are_averaged_not_overwritten_or_counted_as_tasks():
    p = rows("h0", {"a": [0, 0, 1], "b": [0, 0, 0]})
    c = rows("h1", {"a": [1, 1, 0], "b": [0, 0, 0]})
    r = compare(p, c, strict=True)
    assert r["per_task_gain"]["a"] == pytest.approx(1 / 3)
    assert r["gain"] == pytest.approx(1 / 6)
    assert r["regressions"] == []
    r = gate(p, c)
    assert not r["accepted"]  # Resampling unchanged task yields a zero lower bound.
    assert r["interval"][0] == 0


def test_clear_gain_reproducible_and_cost_cap_enforced():
    p = rows("h0", {"a": [0] * 3, "b": [0] * 3})
    c = rows("h1", {"a": [1] * 3, "b": [1] * 3})
    r = gate(p, c)
    assert r["accepted"] and r["interval"] == [1, 1]
    assert gate(p[::-1], c[::-1]) == r
    for row in c:
        row["cost"]["input_tokens"] = 21
    assert gate(p, c)["reason"] == "cost_cap_exceeded"
    c[0]["cost"]["input_tokens"] = None
    assert gate(p, c)["status"] == "inconclusive"


@pytest.mark.parametrize(
    "field,value",
    [
        ("harness_id", "other"),
        ("initial_state_id", "dirty"),
        ("budget_id", "larger"),
        ("protocol_id", "other"),
    ],
)
def test_incompatible_comparisons_rejected(field, value):
    p = rows("h0", {"a": [0] * 3, "b": [0] * 3})
    c = rows("h1", {"a": [1] * 3, "b": [1] * 3})
    c[0][field] = value
    with pytest.raises(ValueError):
        gate(p, c)


def test_missing_repeat_and_environment_failure():
    p = rows("h0", {"a": [0] * 3, "b": [0] * 3})
    c = rows("h1", {"a": [1] * 3, "b": [1] * 3})
    with pytest.raises(ValueError):
        gate(p, c[:-1])
    c[0]["status"] = "environment_error"
    assert gate(p, c)["status"] == "inconclusive"

from copy import deepcopy

import pytest

from mm_harness.core.artifacts import read_json
from mm_harness.evolution.minibatch import Pending, compare, run_round
from mm_harness.evolution.source_versions import review, snapshot, verify


def row(**changes):
    return {
        "task_id": "t",
        "sample": 0,
        "split": "exploration",
        "model_id": "M",
        "protocol_id": "E",
        "harness_id": "H0",
        "status": "success",
        "score": 1,
        **changes,
    }


def test_batch_strict_dev_allows_tie_and_records_regression():
    p = [row(task_id="a", score=1), row(task_id="b", score=0)]
    c = [row(task_id="a", score=0), row(task_id="b", score=1)]
    assert not compare(p, c, strict=True)["passed"]
    assert compare(p, c, strict=False)["passed"]
    assert compare(p, c, strict=False)["regressions"] == ["a"]
    c[0]["status"] = "environment_error"
    assert compare(p, c, strict=False)["status"] == "inconclusive"


@pytest.mark.parametrize(
    "key,value",
    [("task_id", "wrong"), ("model_id", "other"), ("protocol_id", "changed"), ("sample", 1)],
)
def test_comparison_identity(key, value):
    with pytest.raises(ValueError):
        compare([row()], [row(**{key: value})], strict=True)


def test_pending_resume_does_not_repeat_proposal_or_finished_rollouts(tmp_path):
    calls, proposals = [], []
    wait = True

    def runner(identity, directory):
        if wait and identity["split"] == "validation":
            raise Pending("queued")
        calls.append(deepcopy(identity))
        return {**identity, "status": "success", "score": int(identity["harness_id"] == "H1")}

    def proposer(parent, evidence, directory):
        assert all(r["split"] == "exploration" for r in evidence)
        proposals.append(parent)
        return {"status": "candidate", "harness_id": "H1"}

    args = dict(
        parent="H0",
        batch=["a"],
        dev=["b"],
        protocol_id="E",
        model_id="M",
        runner=runner,
        proposer=proposer,
    )
    with pytest.raises(Pending):
        run_round(tmp_path, **args)
    assert len(calls) == 2
    wait = False
    result = run_round(tmp_path, **args)
    assert result["status"] == "accepted" and result["selected"] == "H1"
    assert len(calls) == 4 and len(proposals) == 1
    assert run_round(tmp_path, **args) == result
    assert len(calls) == 4
    with pytest.raises(ValueError, match="Resume inputs differ"):
        run_round(tmp_path, **{**args, "model_id": "different"})


def test_no_gain_never_spends_dev_rollouts(tmp_path):
    calls = []

    def runner(identity, directory):
        calls.append(identity)
        return {**identity, "status": "task_failure", "score": 0}

    state = run_round(
        tmp_path,
        parent="H0",
        batch=["a"],
        dev=["b"],
        protocol_id="E",
        model_id="M",
        runner=runner,
        proposer=lambda *_: {"status": "candidate", "harness_id": "H1"},
    )
    assert state["status"] == "batch_rejected" and state["selected"] == "H0"
    assert len(calls) == 2 and all(r["split"] == "exploration" for r in calls)
    assert read_json(tmp_path / "round.json")["proposal"]["harness_id"] == "H1"


def test_wrong_harness_result_is_not_accepted(tmp_path):
    with pytest.raises(ValueError, match="wrong task/version"):
        run_round(
            tmp_path,
            parent="H0",
            batch=["a"],
            dev=["b"],
            protocol_id="E",
            model_id="M",
            runner=lambda identity, _: {**identity, "harness_id": "wrong"},
            proposer=lambda *_: {},
        )


def test_real_source_snapshot_independent_and_patch_review(tmp_path):
    source = tmp_path / "upstream"
    source.mkdir()
    (source / "agent.py").write_text("def run():\n    return 1\n")
    (source / "scorer.py").write_text("score = 1\n")
    h0 = snapshot(source, tmp_path / "h0")
    snapshot(tmp_path / "h0/source", tmp_path / "candidate", parent=h0["id"])
    child = tmp_path / "candidate/source"
    (child / "agent.py").write_text("def run():\n    return 2\n")
    report = review(tmp_path / "h0", child, allowed=["agent.py"])
    assert report["valid"] and "return 2" in report["patch"]
    assert verify(tmp_path / "h0")["id"] == h0["id"]
    with pytest.raises(ValueError, match="changed after freezing"):
        verify(tmp_path / "candidate")
    (child / "scorer.py").write_text("score = 100\n")
    assert not review(tmp_path / "h0", child, allowed=["agent.py"])["valid"]


def test_pending_parallel_limit_and_completed_result_reuse(tmp_path):
    started, finished = set(), set()

    def runner(identity, directory):
        task = identity["task_id"]
        started.add(task)
        if task not in finished:
            raise Pending(task)
        return {**identity, "status": "task_failure", "score": 0}

    args = dict(
        parent="H0",
        batch=["a", "b", "c"],
        dev=["v"],
        protocol_id="e",
        model_id="m",
        runner=runner,
        proposer=lambda *_: {"status": "no_change"},
        max_parallel_rollouts=2,
    )
    with pytest.raises(Pending):
        run_round(tmp_path, **args)
    assert started == {"a", "b"}
    finished.add("a")
    with pytest.raises(Pending):
        run_round(tmp_path, **args)
    assert started == {"a", "b", "c"}
    assert len(read_json(tmp_path / "round.json")["attempts"]) == 1
    finished.update({"b", "c"})
    assert run_round(tmp_path, **args)["status"] == "no_change"

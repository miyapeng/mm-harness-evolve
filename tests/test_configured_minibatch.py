import pytest

from mm_harness.core.artifacts import read_json
from mm_harness.evolution.minibatch import Pending, plan_batches, run_configured_round


def inputs():
    return dict(
        evolution_batch_size=4,
        validation_batch_size=4,
        task_sampling_seed=42,
        candidates_per_round=1,
        rollouts_per_task=1,
    ), dict(
        upstream_split="dev",
        exploration=[f"e{i}" for i in range(10)],
        validation=[f"v{i}" for i in range(8)],
        test_frozen_only=["reserved"],
    )


def test_pools_are_traversed_and_tail_is_not_padded():
    config, split = inputs()
    plans = [plan_batches(config=config, split=split, round_index=i) for i in range(3)]
    assert [len(p["exploration"]) for p in plans] == [4, 4, 2]
    assert sorted(t for p in plans for t in p["exploration"]) == sorted(split["exploration"])
    assert set(plans[0]["validation"]).isdisjoint(plans[1]["validation"])
    assert plans[2]["validation_epoch"] == 1
    split["upstream_split"] = "test"
    with pytest.raises(ValueError, match="official development"):
        plan_batches(config=config, split=split, round_index=0)


@pytest.mark.parametrize("e_size,v_size", [(4, 4), (2, 3)])
def test_sizes_drive_real_controller_callbacks_and_resume(tmp_path, e_size, v_size):
    config, split = inputs()
    config.update(evolution_batch_size=e_size, validation_batch_size=v_size)
    calls, proposals = [], []
    pending = True

    def runner(identity, directory):
        if pending and identity["split"] == "validation":
            raise Pending("waiting")
        calls.append(identity)
        return {**identity, "status": "success", "score": int(identity["harness_id"] == "h1")}

    def proposer(parent, evidence, directory):
        assert len(evidence) == e_size
        assert all(r["split"] == "exploration" for r in evidence)
        proposals.append(parent)
        return {"status": "candidate", "harness_id": "h1"}

    kwargs = dict(
        config=config,
        split=split,
        round_index=0,
        parent="h0",
        protocol_id="p",
        model_id="m",
        runner=runner,
        proposer=proposer,
    )
    with pytest.raises(Pending):
        run_configured_round(tmp_path, **kwargs)
    plan = read_json(tmp_path / "batch-plan.json")
    assert len(calls) == 2 * e_size
    pending = False
    assert run_configured_round(tmp_path, **kwargs)["selected"] == "h1"
    assert len(calls) == 2 * (e_size + v_size)
    assert len(proposals) == 1
    assert read_json(tmp_path / "batch-plan.json") == plan
    for split_name, size in (("exploration", e_size), ("validation", v_size)):
        parent = {
            r["task_id"] for r in calls if r["split"] == split_name and r["harness_id"] == "h0"
        }
        child = {
            r["task_id"] for r in calls if r["split"] == split_name and r["harness_id"] == "h1"
        }
        assert len(parent) == size and parent == child
    config["validation_batch_size"] += 1
    with pytest.raises(ValueError, match="Resume sampling inputs differ"):
        run_configured_round(tmp_path, **kwargs)

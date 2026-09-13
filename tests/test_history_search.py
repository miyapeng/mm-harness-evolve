from pathlib import Path

import pytest

from experiments.fixtures.history_search import make_fixture
from mm_harness.core.artifacts import read_json
from mm_harness.evolution.history import build_history_workspace
from mm_harness.evolution.minibatch import Pending
from mm_harness.evolution.search import run_search


def setup_search(tmp_path, monkeypatch, mode="multimodal"):
    *values, fake_claude = make_fixture(tmp_path, mode)
    monkeypatch.setattr("mm_harness.evolution.source_proposer.run_claude", fake_claude)
    return values


@pytest.mark.parametrize("mode", ["text", "multimodal"])
def test_three_rounds_rejections_history_pixels_and_selected_parent(tmp_path, monkeypatch, mode):
    kwargs, calls, b_calls, _, h0 = setup_search(tmp_path, monkeypatch, mode)
    result = run_search(**kwargs)
    assert [r["status"] for r in result["rounds"]] == ["accepted", "batch_rejected", "dev_rejected"]
    assert b_calls[0] == h0["id"] and b_calls[1] == b_calls[2] == result["selected"]
    assert len(calls) == 16 + 8 + 16
    assert len({c["sampling_id"] for c in calls}) == 40
    assert result["selected"] == result["rounds"][0]["candidate"]
    assert read_json(tmp_path / "search/selection.json")["test_evaluated"] is False
    graph = read_json(tmp_path / "search/lineage.json")
    assert [edge["parent"] for edge in graph["edges"]] == ["H0", "attempt0", "attempt0"]
    assert len(graph["nodes"]) == 4
    assert run_search(**kwargs) == result
    assert len(calls) == 40 and len(b_calls) == 3


def test_pending_resume_preserves_proposal_and_history_then_continues(tmp_path, monkeypatch):
    kwargs, calls, b_calls, controls, _ = setup_search(tmp_path, monkeypatch)
    controls["pending"] = True
    with pytest.raises(Pending):
        run_search(**kwargs)
    assert len(calls) == 8 and len(b_calls) == 1
    controls["pending"] = False
    state = run_search(**kwargs, round_limit=1)
    assert len(calls) == 16 and len(b_calls) == 1
    assert len(state["rounds"]) == 1
    state = run_search(**kwargs)
    assert len(state["rounds"]) == 3 and len(calls) == 40 and len(b_calls) == 3


def test_frozen_history_and_configuration_cannot_change_on_resume(tmp_path, monkeypatch):
    kwargs, _, _, _, _ = setup_search(tmp_path, monkeypatch)
    result = run_search(**kwargs, round_limit=1)
    entry = result["rounds"][0]["archive"]
    with pytest.raises(ValueError, match="mode differs"):
        build_history_workspace([entry], workspace=tmp_path / "text-preview", mode="text")
    changed = {**kwargs, "config": {**kwargs["config"], "validation_batch_size": 2}}
    with pytest.raises(ValueError, match="resume configuration"):
        run_search(**changed)
    (Path(entry["directory"]) / "harness.patch").write_text("tampered")
    with pytest.raises(ValueError, match="archive changed"):
        run_search(**kwargs)


def test_b_cannot_change_history_even_without_runtime_sandbox(tmp_path, monkeypatch):
    kwargs, _, _, _, _ = setup_search(tmp_path, monkeypatch)
    run_search(**kwargs, round_limit=1)
    from mm_harness.evolution import source_proposer

    original = source_proposer.run_claude

    def tamper(*args):
        original(*args)
        (args[1] / "history/index.json").write_text("{}")

    monkeypatch.setattr(source_proposer, "run_claude", tamper)
    with pytest.raises(ValueError, match="History workspace changed"):
        run_search(**kwargs, round_limit=1)


def test_declared_gate_is_not_silently_ignored(tmp_path, monkeypatch):
    kwargs, calls, _, _, _ = setup_search(tmp_path, monkeypatch)
    kwargs["config"]["batch_gate"] = "accept_everything"
    with pytest.raises(ValueError, match="Unsupported batch_gate"):
        run_search(**kwargs)
    assert not calls


@pytest.mark.parametrize(
    "control,status",
    [("no_change", "no_change"), ("invalid", "invalid"), ("environment", "inconclusive")],
)
def test_unaccepted_attempts_are_archived_without_validation(
    tmp_path, monkeypatch, control, status
):
    kwargs, calls, b_calls, controls, h0 = setup_search(tmp_path, monkeypatch)
    controls[control] = True
    result = run_search(**kwargs, round_limit=1)
    assert result["rounds"][0]["status"] == status and result["selected"] == h0["id"]
    assert len(calls) == 4 and all(c["split"] == "exploration" for c in calls)
    record = read_json(Path(result["rounds"][0]["archive"]["directory"]) / "record.json")
    assert not record["validation_summary"]
    if control == "invalid":
        assert (Path(result["rounds"][0]["archive"]["directory"]) / "harness.patch").is_file()

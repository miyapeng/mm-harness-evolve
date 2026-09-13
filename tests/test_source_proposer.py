import json
import subprocess

import pytest

from mm_harness.core.artifacts import write_json
from mm_harness.evolution.source_proposer import propose_source
from mm_harness.evolution.source_versions import review, snapshot


def test_harness_patch_without_trailing_newline_applies(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.txt").write_text("old")
    snapshot(source, tmp_path / "parent")
    (source / "prompt.txt").write_text("new")
    result = review(tmp_path / "parent", source, allowed=["prompt.txt"])
    patch = tmp_path / "change.patch"
    patch.write_text(result["patch"])
    subprocess.run(
        ["git", "apply", "--check", str(patch)], cwd=tmp_path / "parent/source", check=True
    )


def test_proposal_excludes_pixels_in_text_condition_and_checks_resume(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.txt").write_text("original\n")
    version = snapshot(source, tmp_path / "parent")
    rollout = tmp_path / "rollout"
    rollout.mkdir()
    event = {
        "task_id": "task",
        "harness_id": version["id"],
        "event_id": "1",
        "media": [],
        "observation": "data:image/png;base64,aGVsbG8=",
    }
    (rollout / "events.jsonl").write_text(json.dumps(event) + "\n")
    outcome = {
        "task_id": "task",
        "harness_id": version["id"],
        "score": 0,
        "status": "task_failure",
        "split": "exploration",
        "rollout": str(rollout),
    }

    def fake_claude(root, workspace, role, base_url, output):
        evidence = (workspace / "evidence/rollout-000/events.json").read_text()
        assert "base64" not in evidence and "aGVsbG8=" not in evidence
        (workspace / "source/prompt.txt").write_text("edited\n")
        write_json(
            workspace / "diagnosis.json",
            {
                "diagnosis_id": "d1",
                "parent_harness_id": version["id"],
                "problem": "Missing observation",
                "hypothesis": "Reobserve after edit",
                "evidence_refs": [{"task_id": "task", "event_id": "1", "sample": 0}],
                "mechanism_check": "A new observation after edit",
            },
        )
        write_json(workspace / "proposal.json", {"status": "candidate", "diagnosis_id": "d1"})

    monkeypatch.setattr("mm_harness.evolution.source_proposer.run_claude", fake_claude)
    kwargs = {
        "root": tmp_path,
        "parent": tmp_path / "parent",
        "outcomes": [outcome],
        "output": tmp_path / "proposal",
        "role": {},
        "base_url": "unused",
        "config": {
            "evidence_mode": "text",
            "max_detailed_failures": 3,
            "max_detailed_successes": 1,
            "mutation_surface": ["prompt.txt"],
        },
    }
    result = propose_source(**kwargs)
    assert result["status"] == "candidate" and result["harness_id"] != version["id"]
    assert propose_source(**kwargs) == result
    outcome["score"] = 1
    with pytest.raises(ValueError, match="different evidence"):
        propose_source(**kwargs)

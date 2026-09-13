from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.evolution.mutation_policy import check_policy
from mm_harness.evolution.source_proposer import propose_source
from mm_harness.evolution.source_versions import review, snapshot

POLICY = read_json(Path(__file__).parents[1] / "configs/evolution/swe-mm-mutation-v1.json")


def baseline():
    return {
        "agent": {
            "templates": {
                "instance_template": "Task {{problem_statement}} in {{working_dir}}",
                "next_step_template": "OBSERVATION {{observation}}",
                "next_step_no_output_template": "No output",
                "disable_image_processing": False,
            },
            "history_processors": [{"type": "image_parsing"}],
            "tools": {
                "registry_variables": {"SUBMIT_REVIEW_MESSAGES": ["Review {{diff}}"]},
                "execution_timeout": 300,
            },
            "model": {"name": "fixed"},
        },
        "instances": {"split": "dev"},
    }


def save(root, data):
    file = root / POLICY["file"]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(yaml.safe_dump(data))


@pytest.mark.parametrize("category", ["observation", "context", "verification"])
def test_approved_mechanisms_and_frozen_model(tmp_path, category):
    original = baseline()
    changed = deepcopy(original)
    if category == "observation":
        changed["agent"]["templates"]["instance_template"] += " Reobserve after visual edits."
    elif category == "context":
        changed["agent"]["history_processors"].insert(0, {"type": "last_n_observations", "n": 5})
    else:
        changed["agent"]["tools"]["registry_variables"]["SUBMIT_REVIEW_MESSAGES"] = [
            "Check the final render after edits. {{diff}}"
        ]
    save(tmp_path / "p", original)
    save(tmp_path / "c", changed)
    assert check_policy(tmp_path / "p", tmp_path / "c", POLICY, category)["valid"]
    changed["agent"]["model"]["name"] = "other"
    save(tmp_path / "c", changed)
    assert not check_policy(tmp_path / "p", tmp_path / "c", POLICY, category)["valid"]


@pytest.mark.parametrize(
    "change", ["budget", "variable", "two_categories", "no_image", "processor"]
)
def test_rejected_boundary_changes(tmp_path, change):
    original = baseline()
    changed = deepcopy(original)
    changed["agent"]["templates"]["instance_template"] += " Reobserve."
    category = "observation"
    if change == "budget":
        changed["agent"]["tools"]["execution_timeout"] = 999
    elif change == "variable":
        changed["agent"]["templates"]["instance_template"] = "Task hidden"
    elif change == "two_categories":
        changed["agent"]["templates"]["next_step_template"] += " Extra"
    else:
        changed = deepcopy(original)
        category = "context"
        changed["agent"]["history_processors"] = (
            [] if change == "no_image" else [{"type": "remove_regex"}, {"type": "image_parsing"}]
        )
    save(tmp_path / "p", original)
    save(tmp_path / "c", changed)
    assert not check_policy(tmp_path / "p", tmp_path / "c", POLICY, category)["valid"]


def test_proposer_receives_policy_and_rejects_out_of_scope_yaml(tmp_path, monkeypatch):
    save(tmp_path / "source", baseline())
    parent = snapshot(tmp_path / "source", tmp_path / "parent")
    write_json(tmp_path / "policy.json", POLICY)
    rollout = tmp_path / "rollout"
    rollout.mkdir()
    (rollout / "events.jsonl").write_text(
        '{"task_id":"t","harness_id":"' + parent["id"] + '","event_id":"e1"}\n'
    )

    def fake_claude(root, workspace, role, base_url, output):
        assert read_json(workspace / "mutation-policy.json")["id"] == POLICY["id"]
        assert read_json(workspace / "experiment-context.json")["batch_size"] == 4
        changed = baseline()
        changed["agent"]["templates"]["instance_template"] += " Reobserve."
        changed["agent"]["tools"]["execution_timeout"] = 999
        save(workspace / "source", changed)
        write_json(
            workspace / "diagnosis.json",
            {
                "diagnosis_id": "d1",
                "parent_harness_id": parent["id"],
                "mechanism_category": "observation",
                "problem": "stale image",
                "hypothesis": "refresh image",
                "evidence_refs": [{"task_id": "t", "event_id": "e1"}],
                "mechanism_check": "new request image",
            },
        )
        write_json(
            workspace / "proposal.json",
            {"status": "candidate", "diagnosis_id": "d1", "mechanism_category": "observation"},
        )

    monkeypatch.setattr("mm_harness.evolution.source_proposer.run_claude", fake_claude)
    result = propose_source(
        root=tmp_path,
        parent=tmp_path / "parent",
        output=tmp_path / "proposal",
        outcomes=[
            dict(
                task_id="t",
                harness_id=parent["id"],
                status="task_failure",
                score=0,
                split="exploration",
                rollout=str(rollout),
            )
        ],
        config=dict(
            benchmark="swe_mm",
            mutation_policy="policy.json",
            evidence_mode="text",
            mutation_surface=[POLICY["file"]],
            evolution_batch_size=4,
        ),
        role={},
        base_url="unused",
    )
    assert result["status"] == "invalid"
    assert "outside the chosen" in " ".join(read_json(Path(result["review"]))["errors"])
    assert Path(result["patch"]).is_file()
    # Source code edits also remain disallowed even if the YAML edit is valid.
    (tmp_path / "proposal/workspace/source/models.py").write_text("model = 'other'\n")
    assert not review(
        tmp_path / "parent", tmp_path / "proposal/workspace/source", allowed=[POLICY["file"]]
    )["valid"]

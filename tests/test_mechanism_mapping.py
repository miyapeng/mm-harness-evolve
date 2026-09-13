"""A declared mechanism must map to the patch actually frozen for execution."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.evolution.mutation_policy import allowed_files, check_policy, resolve_policy
from mm_harness.evolution.source_proposer import propose_source
from mm_harness.evolution.source_versions import review, snapshot, verify

ROOT = Path(__file__).parents[1]
CONFIG = read_json(ROOT / "configs/evolution/swe-mm-pilot.json")
POLICY = resolve_policy(ROOT, CONFIG)


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def changes(*pairs):
    return {
        name: {"categories": categories, "reason": "Implement the same hypothesis"}
        for name, categories in pairs
    }


@pytest.mark.parametrize(
    "category,path",
    [
        ("prompt_context", "sweagent/agent/agents.py"),
        ("visual_observation", "tools/image_tools/bin/view_image"),
        ("history_memory", "sweagent/agent/history_processors.py"),
        ("tool_orchestration", "sweagent/tools/parsing.py"),
        ("retry_stop", "sweagent/agent/agents.py"),
        ("internal_verification", "tools/review_on_submit_m/bin/submit"),
    ],
)
def test_six_categories_accept_mapped_code(tmp_path, category, path):
    put(tmp_path / "old", path, "#!/usr/bin/env python\nstrategy = 'old'\n")
    snapshot(tmp_path / "old", tmp_path / "parent")
    put(tmp_path / "new", path, "#!/usr/bin/env python\nstrategy = 'new'\n")
    report = check_policy(
        tmp_path / "old", tmp_path / "new", POLICY, category, changes((path, [category]))
    )
    assert report["valid"]
    assert report["semantic_contracts_verified"] is False
    assert review(tmp_path / "parent", tmp_path / "new", allowed=allowed_files(POLICY))["valid"]


def test_supporting_memory_edit_and_undeclared_files(tmp_path):
    image = "tools/image_tools/bin/view_image"
    history = "sweagent/agent/history_processors.py"
    for path in (image, history):
        put(tmp_path / "old", path, "# before\n")
        put(tmp_path / "new", path, "# after\n")
    mapping = changes((image, ["visual_observation"]), (history, ["history_memory"]))
    report = check_policy(tmp_path / "old", tmp_path / "new", POLICY, "visual_observation", mapping)
    assert report["valid"] and report["supporting_categories"] == ["history_memory"]
    del mapping[history]
    assert not check_policy(
        tmp_path / "old", tmp_path / "new", POLICY, "visual_observation", mapping
    )["valid"]


@pytest.mark.parametrize("violation", ["unmapped_model", "wrong_category", "missing_map"])
def test_declared_label_does_not_authorize_arbitrary_files(tmp_path, violation):
    path = (
        "sweagent/agent/models.py"
        if violation == "unmapped_model"
        else "sweagent/agent/history_processors.py"
    )
    put(tmp_path / "old", path, "# before\n")
    put(tmp_path / "new", path, "# after\n")
    mapping = None if violation == "missing_map" else changes((path, ["visual_observation"]))
    assert not check_policy(
        tmp_path / "old", tmp_path / "new", POLICY, "visual_observation", mapping
    )["valid"]


@pytest.mark.parametrize("violation", [None, "budget", "task_input", "undeclared_category"])
def test_yaml_fields_preserve_fixed_conditions(tmp_path, violation):
    before = {
        "agent": {
            "templates": {
                "system_template": "Help with {{task}}",
                "instance_template": "{{problem_statement}}",
                "next_step_template": "{{observation}}",
                "next_step_no_output_template": "Continue",
            },
            "history_processors": [{"type": "image_parsing"}],
            "model": {"max_calls": 10},
        }
    }
    after = deepcopy(before)
    after["agent"]["templates"]["system_template"] += " Check the current evidence."
    if violation == "budget":
        after["agent"]["model"]["max_calls"] = 20
    elif violation == "task_input":
        after["agent"]["templates"]["instance_template"] = "No task"
    elif violation == "undeclared_category":
        after["agent"]["history_processors"] = []
    path = POLICY["yaml_file"]
    put(tmp_path / "old", path, yaml.safe_dump(before))
    put(tmp_path / "new", path, yaml.safe_dump(after))
    report = check_policy(
        tmp_path / "old",
        tmp_path / "new",
        POLICY,
        "prompt_context",
        changes((path, ["prompt_context"])),
    )
    assert report["valid"] == (violation is None)


def test_non_swe_non_yaml_mapping_uses_same_contract(tmp_path):
    policy = deepcopy(POLICY)
    policy.pop("yaml_file")
    policy["benchmark"] = "fixture_desktop"
    for category in policy["categories"].values():
        category.update(files=["desktop_loop.py"], yaml_paths=[])
    write_json(tmp_path / "mapping.json", policy)
    write_json(tmp_path / policy["taxonomy"], POLICY["shared_contract"])
    resolved = resolve_policy(tmp_path, {"mutation_policy": "mapping.json"})
    assert allowed_files(resolved) == ["desktop_loop.py"]
    put(tmp_path / "old", "desktop_loop.py", "# old\n")
    put(tmp_path / "new", "desktop_loop.py", "# new\n")
    assert check_policy(
        tmp_path / "old",
        tmp_path / "new",
        resolved,
        "retry_stop",
        changes(("desktop_loop.py", ["retry_stop"])),
    )["valid"]


def test_proposer_supplies_contract_and_freezes_mapped_code(tmp_path, monkeypatch):
    path = "sweagent/agent/history_processors.py"
    put(tmp_path / "source", path, "keep = 1\n")
    parent = snapshot(tmp_path / "source", tmp_path / "parent")
    write_json(tmp_path / "policy.json", POLICY)
    write_json(tmp_path / POLICY["taxonomy"], POLICY["shared_contract"])
    put(
        tmp_path / "rollout",
        "events.jsonl",
        '{"task_id":"t","harness_id":"' + parent["id"] + '","event_id":"e1"}\n',
    )

    def fake_claude(root, workspace, role, base_url, output):
        supplied = read_json(workspace / "mutation-policy.json")
        assert supplied["shared_contract"]["categories"].keys() == POLICY["categories"].keys()
        assert path in read_json(workspace / "overview.json")["allowed_edits"]
        write_json(
            workspace / "diagnosis.json",
            {
                "diagnosis_id": "d1",
                "parent_harness_id": parent["id"],
                "mechanism_category": "history_memory",
                "problem": "missing recent observation",
                "hypothesis": "retain more observations",
                "evidence_refs": [{"event_id": "e1"}],
                "mechanism_check": "inspect the next actual request",
            },
        )
        put(workspace / "source", path, "keep = 2\n")
        write_json(
            workspace / "proposal.json",
            {
                "status": "candidate",
                "diagnosis_id": "d1",
                "mechanism_category": "history_memory",
                "change_map": changes((path, ["history_memory"])),
            },
        )

    monkeypatch.setattr("mm_harness.evolution.source_proposer.run_claude", fake_claude)
    kwargs = dict(
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
                rollout=str(tmp_path / "rollout"),
            )
        ],
        config=dict(
            benchmark="swe_mm",
            mutation_policy="policy.json",
            evidence_mode="text",
            evolution_batch_size=4,
        ),
        role={},
        base_url="unused",
    )
    result = propose_source(**kwargs)
    assert result["status"] == "candidate"
    assert verify(Path(result["version_dir"]))["parent"] == parent["id"]
    assert (Path(result["version_dir"]) / "source" / path).read_text() == "keep = 2\n"
    assert (tmp_path / "parent/source" / path).read_text() == "keep = 1\n"
    contract = deepcopy(POLICY["shared_contract"])
    contract["candidate_rule"] = "A changed protocol requires a new experiment"
    write_json(tmp_path / POLICY["taxonomy"], contract)
    with pytest.raises(ValueError, match="different evidence"):
        propose_source(**kwargs)


def test_extensionless_python_tool_syntax_is_checked(tmp_path):
    path = "tools/bin/observe"
    put(tmp_path / "old", path, "#!/usr/bin/env python\nprint('old')\n")
    snapshot(tmp_path / "old", tmp_path / "parent")
    put(tmp_path / "new", path, "#!/usr/bin/env python\ndef broken(\n")
    assert not review(tmp_path / "parent", tmp_path / "new", allowed=[path])["valid"]

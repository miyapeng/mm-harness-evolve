import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pytest

from benchmarks.agentic_vbench.discovery import discover as video_tasks
from benchmarks.browsecomp_v3.discovery import discover as browsing_tasks
from mm_harness.core.artifacts import read_json
from mm_harness.core.benchmarks import check_configuration, mechanism_profile

ROOT = Path(__file__).resolve().parents[1]


def test_agentic_discovery_defaults_to_paper_families_and_no_solution(tmp_path):
    for family in ("repair", "understanding"):
        task = tmp_path / "tasks" / f"agentic_vbench_{family}" / "task1"
        (task / "steps/solve/solution").mkdir(parents=True)
        (task / "task.toml").write_text('version = "1.0"\n')
        (task / "steps/solve/instruction.md").write_text("Repair the supplied audio")
        (task / "steps/solve/solution/solve.sh").write_text("SECRET ORACLE")
    rows = video_tasks(tmp_path)
    assert len(rows) == 1 and rows[0].group == "repair"
    assert len(video_tasks(tmp_path, include_extra_families=True)) == 2
    assert rows[0].split == "unassigned" and not rows[0].payload["development_approved"]
    assert "SECRET" not in json.dumps(asdict(rows[0]))


def test_browsing_discovery_exports_question_images_not_grading_answers(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images/one.png").write_bytes(b"image fixture")
    sample = {
        "id": "q1",
        "question": "Find this building",
        "answer": "SECRET_ANSWER",
        "sub_goals": ["SECRET_SUBGOAL"],
        "metadata": {"images": ["images/one.png"], "solution": "SECRET_METADATA"},
    }
    (tmp_path / "q1.json").write_text(json.dumps(sample))
    rows = browsing_tasks(tmp_path)
    assert rows[0].payload["agent_input"]["images"][0]["sha256"]
    assert "SECRET" not in json.dumps(asdict(rows[0]))
    assert rows[0].split == "unassigned"
    sample["metadata"]["images"] = ["q1.json"]
    (tmp_path / "q1.json").write_text(json.dumps(sample))
    with pytest.raises(ValueError, match="images/"):
        browsing_tasks(tmp_path)


def test_new_sources_have_locks_but_no_executable_rollout_configuration():
    lock = read_json(ROOT / "third_party/lock.json")["upstreams"]
    for benchmark, upstream in [
        ("agentic_vbench", "AgenticVBench"),
        ("browsecomp_v3", "BrowseComp-V3"),
    ]:
        source = read_json(ROOT / f"benchmarks/{benchmark}/upstream/SOURCE.json")
        assert source["commit"] == lock[upstream]["commit"] and len(source["archive_sha256"]) == 64
        config = read_json(ROOT / f"configs/benchmarks/{benchmark}.json")
        assert not check_configuration(config)["configured"]
        assert mechanism_profile(benchmark).integration_status == "source_integrated"
        boundary = read_json(ROOT / f"benchmarks/{benchmark}/mutation-boundary.json")
        assert boundary["mutable"] == []


def test_actual_pinned_agentic_source_discovery_when_restored():
    lock = read_json(ROOT / "third_party/lock.json")["upstreams"]["AgenticVBench"]
    source = ROOT / lock["path"]
    if not source.exists():
        pytest.skip("Restore AgenticVBench source for static source contract")
    assert Counter(t.group for t in video_tasks(source)) == {
        "repair": 18,
        "assembly": 18,
        "sequencing": 28,
        "repurpose": 36,
    }
    assert len(video_tasks(source, include_extra_families=True)) == 124

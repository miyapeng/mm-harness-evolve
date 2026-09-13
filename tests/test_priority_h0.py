import hashlib
import json
from pathlib import Path

import pytest
from benchmarks.claw_eval_mm.launch_h0 import batch_command

from benchmarks.swe_mm.launch_h0 import command as swe_command
from benchmarks.swe_mm.prepare_inputs import convert
from benchmarks.vision2web.launch_h0 import command as vision_command

ROOT = Path(__file__).resolve().parents[1]


def test_official_h0_copies_match_source_manifests():
    for name in ("swe_mm", "vision2web", "claw_eval_mm"):
        directory = ROOT / "benchmarks" / name / "upstream"
        source = json.loads((directory / "SOURCE.json").read_text())
        assert source["modifications"] == []
        for relative in source["copied_files"]:
            assert (
                hashlib.sha256((directory / relative).read_bytes()).hexdigest()
                == source["files"][relative]
            )


def test_swe_conversion_preserves_only_actor_inputs_and_verified_image():
    row = {
        "instance_id": "org__repo-1",
        "base_commit": "base",
        "problem_statement": "issue",
        "images": [{"source_url": "https://example.org/issue.png"}],
        "patch": "PRIVATE ANSWER",
        "test_patch": "PRIVATE TEST",
    }
    mirrors = {
        row["instance_id"]: {
            "status": "mirrored",
            "source_digest": "sha256:abc",
            "target_digest": "sha256:abc",
            "target": "registry/repo:tag",
        }
    }
    result = convert([row], mirrors)[0]
    assert "PRIVATE" not in json.dumps(result)
    assert result["extra_fields"] == {"issue_images": ["https://example.org/issue.png"]}
    assert result["image_name"] == "registry/repo:tag@sha256:abc"
    mirrors[row["instance_id"]]["target_digest"] = "sha256:changed"
    with pytest.raises(ValueError, match="Unverified instance image"):
        convert([row], mirrors)


def test_native_launchers_use_repository_sources_and_official_entrypoints(tmp_path):
    (tmp_path / "third_party").mkdir()
    (tmp_path / "third_party/lock.json").write_bytes((ROOT / "third_party/lock.json").read_bytes())
    data = tmp_path / "data/vision2web"
    data.mkdir(parents=True)
    (data / "image.json").write_text(
        json.dumps({"immutable_image": "registry/v2w:official", "target_digest": "sha256:fixed"})
    )
    cwd, argv = swe_command(
        tmp_path,
        instance_id="org__repo.js-1",
        model_config=tmp_path / "model.yaml",
        output=tmp_path / "runs/swe",
    )
    assert cwd.is_relative_to(tmp_path)
    assert argv[argv.index("--config") + 1] == str(cwd / "config/default_mm_with_images.yaml")
    assert argv[argv.index("--instances.filter") + 1] == r"^org__repo\.js\-1$"
    cwd, argv = vision_command(
        tmp_path,
        task_type="frontend",
        project="project",
        model="model",
        base_url="http://model.invalid/v1",
        output=tmp_path / "runs/vision",
    )
    assert cwd.is_relative_to(tmp_path)
    assert argv[argv.index("--framework") + 1] == "openhands"
    assert argv[argv.index("--datasets-dir") + 1] == str(data / "extracted")
    assert "--prompt" not in argv


def test_claw_single_task_cannot_expand_to_other_tasks(tmp_path):
    task = tmp_path / "tasks/M001_example"
    task.mkdir(parents=True)
    (task / "task.yaml").write_text("tags: [multimodal]\n")
    argv = batch_command(tmp_path, tmp_path / "config.yaml", tmp_path / "out", task_id=task.name)
    assert argv[-2:] == ["--filter", task.name]
    (tmp_path / "tasks/M001_example_variant").mkdir()
    with pytest.raises(ValueError, match="exactly one"):
        batch_command(tmp_path, tmp_path / "config.yaml", tmp_path / "out", task_id=task.name)

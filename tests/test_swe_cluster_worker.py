import base64
import json

import pytest

from benchmarks.swe_mm import cluster_runner
from mm_harness.core.artifacts import write_json
from mm_harness.evolution.rollout_workspace import build_rollout_workspace


def test_export_actual_request_pixels_and_no_private_scorer(tmp_path):
    identity = dict(
        task_id="task",
        harness_id="version",
        split="exploration",
        sample=0,
        protocol_id="protocol",
        model_id="qwen",
        round_index=0,
        sampling_id="sample",
    )
    rollout = tmp_path / "rollout"
    call = rollout / "requests/call-0000"
    pixels = b"actual outgoing image bytes"
    write_json(
        call / "request.json",
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(pixels).decode()
                            },
                        }
                    ],
                }
            ]
        },
    )
    write_json(
        call / "response.raw",
        {
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            "choices": [{"message": {"tool_calls": [{"id": "tool"}]}}],
        },
    )
    write_json(
        rollout / "native/task.traj", {"trajectory": [{"action": "bash", "observation": "ok"}]}
    )
    (rollout / "prediction.patch").write_text("a real patch")
    write_json(tmp_path / "scorer-private/report.json", {"reference_answer": "NEVER_EXPORT"})
    result = cluster_runner.export(
        identity, tmp_path, {"trajectory": "native/task.traj", "seconds": 1}, {"resolved": True}
    )
    assert result["status"] == "success"
    assert result["cost"]["input_tokens"] == 12
    assert result["cost"]["image_presentations"] == 1
    workspace = tmp_path / "workspace"
    build_rollout_workspace(
        [result], parent_id="version", workspace=workspace, mode="multimodal", allowed_edits=[]
    )
    assert any(p.read_bytes() == pixels for p in workspace.rglob("*.png"))
    assert "NEVER_EXPORT" not in "".join(p.read_text() for p in workspace.rglob("*.json"))


def test_resume_rejects_wrong_sampling_identity(tmp_path):
    source = tmp_path / "source"
    write_json(
        tmp_path / "actor-request.json", {"identity": {"task_id": "other"}, "source": str(source)}
    )
    with pytest.raises(ValueError, match="identity/source"):
        cluster_runner.run_and_score({"task_id": "wanted"}, source, tmp_path)


def test_job_submission_is_not_repeated_on_resume(tmp_path, monkeypatch):
    calls = []

    def remote(args):
        calls.append(args)
        return type(
            "Response", (), {"returncode": 0, "stdout": "JobStatus.RUNNING", "stderr": ""}
        )()

    monkeypatch.setattr(cluster_runner, "remote", remote)
    for _ in range(2):
        with pytest.raises(cluster_runner.Pending):
            cluster_runner.job(tmp_path, "actor", "image@sha256:fixed", ["python", "run.py"])
    assert [call[0] for call in calls] == ["run", "get-job"]
    assert json.loads((tmp_path / "actor-job.json").read_text())["image"] == "image@sha256:fixed"


def test_gif_adapter_retains_original_and_indexes_transmitted_frames(tmp_path):
    from PIL import Image

    from mm_harness.core.artifacts import file_digest

    raw = tmp_path / "raw.gif"
    frames = [Image.new("RGB", (4, 4), color) for color in ("red", "green", "blue")]
    frames[0].save(raw, save_all=True, append_images=frames[1:], duration=100)
    output = tmp_path / "public"
    output.mkdir()
    sha = file_digest(raw)
    refs = cluster_runner.stage_issue_image(
        {"url": "https://example.org/issue.gif", "sha256": sha, "content_type": "image/gif"},
        raw,
        output,
    )
    assert [r["frame_index"] for r in refs] == [0, 1, 2]
    assert [r["timestamp_ms"] for r in refs] == [0, 100, 200]
    assert file_digest(output / "raw.gif") == sha
    assert [Image.open(output / r["filename"]).getpixel((0, 0)) for r in refs] == [
        (255, 0, 0),
        (0, 128, 0),
        (0, 0, 255),
    ]
    assert all(file_digest(output / r["filename"]) == r["sha256"] for r in refs)


@pytest.mark.parametrize(
    "exit_status", ["submitted (exit_error)", "submitted (exit_environment_error)"]
)
def test_wrapped_runtime_failure_is_not_counted_as_task_failure(tmp_path, monkeypatch, exit_status):
    identity = dict(task_id="task", harness_id="h0", split="exploration", sample=0)
    source = tmp_path / "source"
    write_json(tmp_path / "actor-request.json", {"identity": identity, "source": str(source)})
    write_json(tmp_path / "rollout/native/task.traj", {"trajectory": []})
    write_json(
        tmp_path / "rollout/actor-result.json",
        {
            "identity": identity,
            "trajectory": "native/task.traj",
            "exit_status": exit_status,
            "seconds": 1,
        },
    )
    result = cluster_runner.run_and_score(identity, source, tmp_path)
    assert result["status"] == "environment_error" and result["score"] is None


def test_incomplete_provider_usage_is_explicitly_a_lower_bound(tmp_path):
    identity = dict(task_id="task", harness_id="h0", split="exploration", sample=0)
    write_json(tmp_path / "rollout/requests/call-0000/request.json", {"messages": []})
    result = cluster_runner.export(
        identity, tmp_path, {"seconds": 1}, {"status": "environment_error"}
    )
    assert result["cost"]["token_accounting"] == "lower_bound"
    assert result["cost"]["unreported_requests"] == 1

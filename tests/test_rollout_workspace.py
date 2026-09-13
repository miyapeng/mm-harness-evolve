import base64
import json

import pytest

from mm_harness.core.artifacts import file_digest, read_json, write_json
from mm_harness.evolution.rollout_workspace import build_rollout_workspace

# Valid tiny PNG for actual Read-compatible material, not a benchmark result.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO1sAAAAASUVORK5CYII="
)


def make_rollout(root, index=0):
    root.mkdir()
    (root / "image.png").write_bytes(PNG)
    event = dict(
        task_id=f"t{index}",
        harness_id="h0",
        event_id="e1",
        kind="observation",
        payload={"code_revision": "abc", "tool_result": "done"},
        media=[
            dict(
                path="image.png",
                sha256=file_digest(root / "image.png"),
                mime_type="image/png",
                role="after_action",
            )
        ],
    )
    (root / "events.jsonl").write_text(json.dumps(event) + "\n")
    write_json(
        root / "request.json",
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(PNG).decode(),
                            },
                        }
                    ],
                }
            ]
        },
    )
    (root / "gold.txt").write_text("PRIVATE_ANSWER")
    return dict(
        task_id=f"t{index}",
        harness_id="h0",
        split="exploration",
        sample=0,
        status="task_failure" if index else "success",
        score=int(not index),
        rollout=str(root),
        feedback={"failed_test_names": ["ui"]},
        evidence_files=[
            dict(
                path="request.json",
                sha256=file_digest(root / "request.json"),
                visibility="evolver",
                kind="model_request",
                format="json",
            )
        ],
    )


@pytest.mark.parametrize("mode", ["text", "multimodal"])
def test_all_tasks_queryable_and_pixel_modes(tmp_path, mode):
    rows = [make_rollout(tmp_path / f"r{i}", i) for i in range(5)]
    workspace = tmp_path / "workspace"
    result = build_rollout_workspace(
        rows, parent_id="h0", workspace=workspace, mode=mode, allowed_edits=["prompt.txt"]
    )
    assert len(result["outcomes"]) == 5  # No truncation to 3 failures / 1 success.
    assert result["all_round_rollouts_available"]
    for record in result["outcomes"]:
        entry = read_json(workspace / record["event_index"])[0]
        event = read_json(workspace / entry["path"])
        media = event["media"][0]
        assert event["payload"]["code_revision"] == "abc"
        request = read_json(workspace / read_json(workspace / record["files"])[0]["path"])
        inline = request["messages"][0]["content"][0]
        if mode == "multimodal":
            assert (workspace / media["path"]).read_bytes() == PNG
            assert (workspace / inline["path"]).read_bytes() == PNG
        else:
            assert media["path"] is None and inline["path"] is None
    for file in workspace.rglob("*.json"):
        assert "PRIVATE_ANSWER" not in file.read_text()
        assert base64.b64encode(PNG).decode() not in file.read_text()
    if mode == "text":
        assert not list(workspace.rglob("*.png"))
    assert not list(workspace.rglob("gold.txt"))


@pytest.mark.parametrize("mutation", ["split", "parent", "digest", "path", "event"])
def test_wrong_or_private_evidence_rejected(tmp_path, mutation):
    row = make_rollout(tmp_path / "r")
    if mutation == "split":
        row["split"] = "validation"
    elif mutation == "parent":
        row["harness_id"] = "h1"
    elif mutation == "digest":
        row["evidence_files"][0]["sha256"] = "wrong"
    elif mutation == "path":
        row["evidence_files"][0]["path"] = "../outside"
    else:
        p = tmp_path / "r/events.jsonl"
        event = json.loads(p.read_text())
        event["task_id"] = "wrong"
        p.write_text(json.dumps(event))
    with pytest.raises(ValueError):
        build_rollout_workspace(
            [row], parent_id="h0", workspace=tmp_path / "w", mode="multimodal", allowed_edits=[]
        )


@pytest.mark.parametrize("mode", ["text", "multimodal"])
def test_inline_request_images_are_indexed_by_event(tmp_path, mode):
    row = make_rollout(tmp_path / "r")
    root = tmp_path / "r"
    event = read_json(root / "events.jsonl")
    event.update(kind="model_request", media=[], payload=read_json(root / "request.json"))
    (root / "events.jsonl").write_text(json.dumps(event) + "\n")
    workspace = tmp_path / "w"
    build_rollout_workspace([row], parent_id="h0", workspace=workspace, mode=mode, allowed_edits=[])
    target = workspace / "evidence/rollout-000"
    index = read_json(target / "media-index.json")
    assert len(index) == 1 and index[0]["event_id"] == "e1"
    ref = read_json(target / "event-index.json")[0]["media"][0]
    assert ref["sha256"] == file_digest(root / "image.png")
    if mode == "multimodal":
        assert (workspace / ref["path"]).read_bytes() == PNG
    else:
        assert ref["path"] is None and not list(workspace.rglob("*.png"))


def test_repeated_native_history_is_preserved_behind_query_reference(tmp_path):
    row = make_rollout(tmp_path / "r")
    root = tmp_path / "r"
    event = read_json(root / "events.jsonl")
    query = [{"role": "user", "content": "UNIQUE_OLD_CONTEXT"}]
    event.update(
        kind="tool_step", payload={"action": "screenshot", "observation": "done", "query": query}
    )
    (root / "events.jsonl").write_text(json.dumps(event) + "\n")
    workspace = tmp_path / "w"
    build_rollout_workspace(
        [row], parent_id="h0", workspace=workspace, mode="multimodal", allowed_edits=[]
    )
    path = workspace / "evidence/rollout-000/events/00000.json"
    exported = read_json(path)
    assert "UNIQUE_OLD_CONTEXT" not in path.read_text()
    assert exported["payload"]["action"] == "screenshot"
    ref = exported["payload"]["query"]
    assert ref["message_count"] == 1 and read_json(workspace / ref["archived_path"]) == query
    index = read_json(workspace / "evidence/rollout-000/trajectory-index.json")
    assert index[0]["excerpts"]["action"] == "screenshot"
    assert workspace / index[0]["path"] == path
    assert index[0]["truncated_fields"] == []

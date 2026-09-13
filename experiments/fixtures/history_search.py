"""Deterministic integration fixture, never a real benchmark or model result."""

import base64
import io
import json

from PIL import Image

from mm_harness.core.artifacts import digest, read_json, tree_manifest, write_json
from mm_harness.evolution.minibatch import Pending
from mm_harness.evolution.source_versions import snapshot

_buffer = io.BytesIO()
Image.new("RGB", (8, 8), "red").save(_buffer, format="PNG")
PIXELS = _buffer.getvalue()


def make_fixture(tmp_path, mode="multimodal"):
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.txt").write_text("0")
    h0 = snapshot(source, tmp_path / "h0")
    calls, b_calls = [], []
    controls = {"pending": False, "no_change": False, "invalid": False, "environment": False}

    def runner(identity, frozen_source, attempt):
        if controls["pending"] and identity["split"] == "validation":
            raise Pending("queued")
        number = int((frozen_source / "prompt.txt").read_text())
        assert digest(tree_manifest(frozen_source)) == identity["harness_id"]
        calls.append(dict(identity))
        if controls["environment"]:
            return {**identity, "status": "environment_error", "score": None}
        attempt.mkdir(parents=True, exist_ok=True)
        event = {
            **identity,
            "event_id": "event-1",
            "message": "fixture E feedback; not an official benchmark result",
            "request": "data:image/png;base64," + base64.b64encode(PIXELS).decode(),
        }
        if identity["split"] == "validation":
            event["message"] = "V_PRIVATE_TRACE_AND_ANSWER"
        (attempt / "events.jsonl").write_text(json.dumps(event) + "\n")
        # First candidate improves. Second ties on E. Third improves E but fails V.
        score = {0: 0, 1: 0.5, 2: 0.5, 3: 1}[number]
        if number == 3 and identity["split"] == "validation":
            score = 0
        return {
            **identity,
            "score": score,
            "status": "success" if score == 1 else "task_failure",
            "rollout": str(attempt),
            "cost": {"input_tokens": 10},
        }

    def fake_claude(root, workspace, role, base_url, output):
        index = len(b_calls)
        overview = read_json(workspace / "overview.json")
        history = read_json(workspace / "history/index.json")
        assert len(history["rounds"]) == index
        assert overview["history_available"] == (index > 0)
        assert "V_PRIVATE_TRACE_AND_ANSWER" not in "".join(
            p.read_text(errors="replace") for p in (workspace / "history").rglob("*") if p.is_file()
        )
        if index:
            previous = workspace / "history/round-000"
            record = read_json(previous / "record.json")
            assert record["exploration_comparison"]["gain"] == 0.5
            assert "per_task_gain" not in record["validation_summary"]
            assert (previous / "parent/source/prompt.txt").read_text() == "0"
            assert (previous / "candidate/source/prompt.txt").read_text() == "1"
            files = list(previous.rglob("*.png"))
            assert bool(files) == (mode == "multimodal")
            if files:
                assert files[0].read_bytes() == PIXELS
        if index == 2:
            assert history["rounds"][1]["status"] == "batch_rejected"
        b_calls.append(overview["parent"])
        diagnosis = {
            "diagnosis_id": f"d{index}",
            "parent_harness_id": overview["parent"],
            "problem": "fixture",
            "hypothesis": "fixture change",
            "evidence_refs": [{"path": "evidence/rollout-000/events/00000.json"}],
            "mechanism_check": "fixture only",
        }
        write_json(workspace / "diagnosis.json", diagnosis)
        if controls["no_change"]:
            write_json(
                workspace / "proposal.json", {"status": "no_change", "reason": "no evidence"}
            )
        else:
            (workspace / "source/prompt.txt").write_text(str(index + 1))
            if controls["invalid"]:
                (workspace / "source/scorer.py").write_text("score = 1\n")
            write_json(
                workspace / "proposal.json", {"status": "candidate", "diagnosis_id": f"d{index}"}
            )
        write_json(output / "usage.json", {"usage": {"input_tokens": 20}, "local_cost_usd": None})

    kwargs = dict(
        root=tmp_path,
        directory=tmp_path / "search",
        h0=tmp_path / "h0",
        config=dict(
            status="deterministic_fixture_not_model_or_benchmark_rollout",
            search_strategy="current_parent_with_history",
            evidence_mode=mode,
            mutation_surface=["prompt.txt"],
            max_rounds=3,
            evolution_batch_size=4,
            validation_batch_size=4,
            candidates_per_round=1,
            rollouts_per_task=1,
            task_sampling_seed=42,
        ),
        split=dict(
            upstream_split="dev",
            exploration=[f"e{i}" for i in range(12)],
            validation=[f"v{i}" for i in range(4)],
            test_frozen_only=["test-secret"],
        ),
        role={},
        base_url="unused",
        model_id="fixture",
        protocol_id="fixture",
        runner=runner,
    )
    return kwargs, calls, b_calls, controls, h0, fake_claude

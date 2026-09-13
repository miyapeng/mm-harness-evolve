import base64
import io
import json
import sys
from types import SimpleNamespace

import pytest

from mm_harness.core.artifacts import digest, read_json
from mm_harness.core.benchmarks import NAMES, adapter_for, benchmark_directory, profile
from mm_harness.core.schema import Cost, Task
from mm_harness.evolution.autosaddler import validated_parent
from mm_harness.evolution.evidence import text_without_pixels
from mm_harness.runtimes.model import ChatModel, ModelError
from mm_harness.runtimes.upstream_hook import execute


def test_real_http_serializer_contains_image_bytes(tmp_path, monkeypatch):
    # Exercise the urllib transport serializer itself, not the injectable model transport.
    import urllib.request

    image = tmp_path / "image.png"
    image.write_bytes(b"pixel fixture")
    captured = []

    class Opener:
        def open(self, request, timeout):
            captured.append(json.loads(request.data))
            return io.BytesIO(
                json.dumps({"model": "m", "choices": [{"message": {"content": "ok"}}]}).encode()
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    client = ChatModel(
        {"base_url": "http://local.invalid", "no_proxy": True},
        {"model": "m", "temperature": 0, "max_tokens": 8, "timeout_seconds": 1},
    )
    client.call("inspect", [{"path": str(image)}], tmp_path / "call", seed=0)
    url = captured[0]["messages"][0]["content"][-1]["image_url"]["url"]
    assert base64.b64decode(url.split(",")[1]) == image.read_bytes()


def test_unknown_cost_request_is_not_silently_resampled(tmp_path):
    calls = []

    def interrupted(body):
        calls.append(body)
        raise ConnectionError("response lost")

    client = ChatModel({}, {"model": "m", "temperature": 0, "max_tokens": 8}, transport=interrupted)
    with pytest.raises(ModelError, match="response lost"):
        client.call("p", [], tmp_path, seed=0)
    with pytest.raises(ModelError, match="Interrupted request"):
        client.call("p", [], tmp_path, seed=0)
    assert len(calls) == 1


def test_all_benchmark_profiles_are_discoverable():
    assert len(NAMES) == 6
    for name in NAMES:
        value = profile(name)
        assert value["benchmark"] == name and value["protocol"]["evaluator_only"]
        adapter = adapter_for(
            {"benchmark": name, "adapter": {**value, "transport": "command"}}, None
        )
        assert adapter.benchmark == name


def test_claw_eval_mm_uses_official_h0_and_filters_multimodal(tmp_path):
    from pathlib import Path

    from benchmarks.claw_eval_mm.launch_h0 import batch_command

    root = Path(__file__).resolve().parents[1]
    spec = profile("claw_eval_mm")
    catalog = read_json(root / spec["dataset"]["catalog"])
    assert catalog["count"] == len(catalog["tasks"]) == spec["dataset"]["code_task_count"]
    assert len({row["task_id"] for row in catalog["tasks"]}) == catalog["count"]
    assert catalog["selection"] == {"tag": "multimodal"}
    assert catalog["source_commit"] == spec["upstream"]["commit"]
    assert not catalog["research_splits_assigned"]
    command = batch_command(tmp_path, tmp_path / "config_multimodal.yaml", tmp_path / "traces")
    assert command[command.index("--tag") + 1] == "multimodal"
    assert command[command.index("--trials") + 1] == "3" and "--sandbox" in command
    files = {
        name: (benchmark_directory("claw_eval_mm", root) / "h0" / name).read_text()
        for name in ("harness.py", "prompt.txt")
    }
    recipe = json.loads(files["prompt.txt"])
    assert (
        recipe["runner"] == "claw_eval.runner.loop:run_task" and recipe["prompt_override"] is None
    )
    request = {
        "harness": {"files": files},
        "harness_id": "sha256:" + digest(files),
        "task_id": "mm",
        "repetition": 0,
        "workspace": str(tmp_path),
    }
    seen = []
    execute(
        request, lambda request: SimpleNamespace(execute_upstream=lambda p: (seen.append(p), {})[1])
    )
    assert seen == [files["prompt.txt"]]
    policy = read_json(root / "archive/configs/evolution/claw_eval_mm.json")
    assert policy["selection"]["success_threshold"] == spec["protocol"]["pass_threshold"]


def test_upstream_hook_executes_candidate_source_and_prompt(tmp_path):
    files = {
        "harness.py": "def run(api):\n    return {'value': api.prompt + ':candidate'}\n",
        "prompt.txt": "new",
    }
    req = {
        "harness": {"files": files},
        "harness_id": "sha256:" + digest(files),
        "task_id": "x",
        "repetition": 0,
        "workspace": str(tmp_path),
    }
    assert execute(req, lambda request: SimpleNamespace())["value"] == "new:candidate"
    req["harness_id"] = "wrong"
    with pytest.raises(ValueError, match="identity"):
        execute(req, lambda request: None)


def test_command_bridge_separates_scoring_inputs_and_checks_identity(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text("""import json, sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text())
o={k:r[k] for k in ('task_id','harness_id','repetition')}
if r['schema_version']=='mm_harness/execute/v1':
    assert 'evaluator_input' not in r and 'private-answer' not in json.dumps(r)
    Path(r['workspace'],'artifact.txt').write_text('generated')
    o.update(status='success',cost={'model_calls':1},events=[],artifacts=[{'path':'artifact.txt'}])
else:
    assert r['evaluator_input']['answer']=='private-answer'
    o.update(status='success',score=0.9,metrics={'native':0.9},evaluator_id=r['evaluator_id'])
if len(sys.argv)>3:o['task_id']='wrong'
Path(sys.argv[2]).write_text(json.dumps(o))
""")
    command = [sys.executable, str(worker), "{request}", "{response}"]
    config = {
        "benchmark": "swe_mm",
        "adapter": {
            "commands": {"execute": command, "score": command},
            "protocol": {"reference_answers_visible": False},
            "evaluator": {"revision": "fixed"},
            "timeout_seconds": 10,
        },
    }
    task = Task(
        "x",
        "swe_mm",
        "exploration",
        "repo",
        {"agent_input": {"instruction": "fix"}, "evaluator_input": {"answer": "private-answer"}},
    )
    harness = tmp_path / "h0"
    harness.mkdir()
    files = {"harness.py": "def run(api): return 1\n", "prompt.txt": "upstream"}
    for name, body in files.items():
        (harness / name).write_text(body)
    model = SimpleNamespace(provider={}, role={})
    version = "sha256:" + digest(files)
    a = adapter_for(config, model)
    result = a.run(task, harness, version, 0, tmp_path / "good")
    assert result.score == 0.9 and result.cost.model_calls == 1
    assert read_json(tmp_path / "good/artifacts.json")[0]["sha256"]
    a.config["commands"]["score"] = [*command, "wrong-task"]
    result = a.run(task, harness, version, 0, tmp_path / "bad")
    assert result.status == "environment_error" and result.score is None
    assert "task_id mismatch" in result.error


def test_next_round_stays_on_incumbent_after_validation_rejection(tmp_path):
    from mm_harness.core.schema import Outcome

    def evaluation(version, score):
        o = Outcome(
            "t",
            version,
            "validation",
            0,
            "success",
            score,
            {},
            Cost(input_tokens=10),
            "judge",
            str(tmp_path),
        )
        return {
            "candidate_id": version,
            "split": "development",
            "iteration": 0,
            "observations": [{"metadata": {"outcome": o.to_dict()}}],
        }

    assert (
        validated_parent(["h0", "bad"], [evaluation("h0", 0.9), evaluation("bad", 0.8)], {}) == "h0"
    )
    assert (
        validated_parent(["h0", "good"], [evaluation("h0", 0.9), evaluation("good", 0.95)], {})
        == "good"
    )


def test_native_inline_pixels_are_not_text_evidence():
    native = {
        "image_url": {"url": "data:image/png;base64,YWJj"},
        "anthropic": {"type": "image", "source": {"type": "base64", "data": "secret-pixels"}},
        "tool_return": "success",
    }
    clean = text_without_pixels(native)
    assert "YWJj" not in json.dumps(clean) and "secret-pixels" not in json.dumps(clean)
    assert clean["tool_return"] == "success" and native["image_url"]["url"].endswith("YWJj")


def test_exported_patch_preserves_missing_terminal_newline(tmp_path):
    import subprocess

    from experiments.summarize import unified_patch

    parent, child = {"prompt.txt": "old\nlast"}, {"prompt.txt": "new\nlast changed"}
    patch = tmp_path / "change.patch"
    patch.write_text(unified_patch(parent, child))
    (tmp_path / "prompt.txt").write_text(parent["prompt.txt"])
    result = subprocess.run(
        ["git", "apply", str(patch)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "prompt.txt").read_text() == child["prompt.txt"]

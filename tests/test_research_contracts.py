import base64
import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from mm_harness.core.media import copy_media, crop_media
from mm_harness.core.schema import Cost, Outcome, Task, validate_splits
from mm_harness.core.store import RunStore, Trace
from mm_harness.evolution.candidates import CandidateStore
from mm_harness.evolution.evidence import build_evidence
from mm_harness.evolution.selection import select
from mm_harness.runtimes.model import ChatModel, assert_same_model


def make_image(path):
    from PIL import Image

    Image.new("RGB", (20, 20), "blue").save(path)
    return path


def model(transport):
    return ChatModel(
        {"base_url": "http://test.invalid", "no_proxy": True},
        {"model": "fixed-vision", "temperature": 0.0, "max_tokens": 100, "timeout_seconds": 5},
        transport=transport,
    )


def answer(body):
    return {
        "model": body["model"],
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }


def outcome(root, split="validation", task="a", version="parent", score=0.9):
    return Outcome(
        task, version, split, 0, "success", score, {}, Cost(input_tokens=20), "judge-v1", str(root)
    )


def test_image_bytes_reach_model_request_and_resume(tmp_path):
    path = make_image(tmp_path / "input.png")
    bodies = []
    client = model(lambda body: (bodies.append(body), answer(body))[1])
    args = ("read the image", [{"path": str(path), "event_id": "e1"}], tmp_path / "call")
    first = client.call(*args, seed=0)
    second = client.call(*args, seed=0)
    assert first == second and len(bodies) == 1
    image = bodies[0]["messages"][0]["content"][-1]
    assert image["type"] == "image_url"
    assert base64.b64decode(image["image_url"]["url"].split(",")[1]) == path.read_bytes()
    assert "Authorization" not in (tmp_path / "call/request.json").read_text()
    with pytest.raises(ValueError, match="different inputs"):
        client.call("changed", [], tmp_path / "call", seed=0)


def test_wrong_model_is_not_counted_as_target(tmp_path):
    with pytest.raises(Exception, match="unexpected model"):
        model(lambda b: {**answer(b), "model": "other"}).call("x", [], tmp_path, seed=0)
    assert not (tmp_path / "response.json").exists()


def test_evidence_conditions_same_text_different_pixels(tmp_path):
    image = make_image(tmp_path / "image.png")
    trace = Trace(tmp_path / "rollout", "a", "parent")
    media = copy_media(image, trace.root, "before")
    trace.add("observation", media=[media], tool_return="success")
    o = outcome(trace.root, "exploration")
    text = build_evidence([o], "text", tmp_path / "text.json")
    visual = build_evidence([o], "multimodal", tmp_path / "visual.json")
    assert text["records"] == visual["records"]
    assert not text["image_index"] and len(visual["image_index"]) == 1
    with pytest.raises(ValueError, match="exploration"):
        build_evidence([replace(o, split="validation")], "text", tmp_path / "bad.json")
    with pytest.raises(ValueError, match="mismatch"):
        build_evidence([replace(o, harness_id="wrong")], "text", tmp_path / "bad.json")


def test_crop_retains_source_and_checks_pixels(tmp_path):
    original = make_image(tmp_path / "blue.png")
    media = copy_media(original, tmp_path, "after")
    crop = crop_media(tmp_path, media, (0, 0, 10, 10))
    assert crop["source_sha256"] == media["sha256"]
    assert crop["sha256"] != media["sha256"]
    with pytest.raises(ValueError):
        crop_media(tmp_path, media, (0, 0, 100, 100))


def test_split_group_and_model_identity():
    tasks = [
        Task("a", "b", "exploration", "same-site", {}),
        Task("b", "b", "validation", "same-site", {}),
    ]
    with pytest.raises(ValueError, match="crosses"):
        validate_splits(tasks)
    a = {"provider": "p", "model": "m", "revision": "v1"}
    with pytest.raises(ValueError, match="A=B"):
        assert_same_model({"roles": {"executor": a, "evolver": {**a, "revision": "v2"}}})


def test_candidates_are_isolated_and_source_controls_execution(tmp_path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "harness.py").write_text('def run(api):\n    return "parent"\n')
    candidates = CandidateStore(tmp_path / "versions", ["harness.py"])
    parent = candidates.seed(baseline)
    child = candidates.apply(
        parent, {"harness.py": 'def run(api):\n    return "child"\n'}, tmp_path / "proposal"
    )
    for name, version in [("parent", parent), ("child", child)]:
        root = candidates.materialize(version, tmp_path / name)
        spec = importlib.util.spec_from_file_location(name, root / "harness.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.run(None) == name
    assert (baseline / "harness.py").read_text().endswith('"parent"\n')
    with pytest.raises(ValueError, match="writable"):
        candidates.apply(child, {"../scorer.py": "bad"}, tmp_path / "bad")
    (tmp_path / "versions" / child / "source/harness.py").write_text("tampered")
    with pytest.raises(ValueError, match="version"):
        candidates.load(child)


def test_selection_checks_identity_regression_cost_and_infra(tmp_path):
    p = outcome(tmp_path)
    c = replace(p, harness_id="child", score=0.95)
    assert select([p], [c])["accepted"]
    assert not select([p], [replace(c, score=0.7)])["accepted"]
    assert not select([p], [replace(c, cost=Cost(input_tokens=1000))])["accepted"]
    assert not select([p], [replace(c, status="timeout", score=None)])["accepted"]
    with pytest.raises(ValueError, match="exact same"):
        select([p], [replace(c, evaluator_id="judge-v2")])
    with pytest.raises(ValueError, match="exact same"):
        select([p], [replace(c, task_id="other")])


def test_resume_drift_and_single_controller(tmp_path):
    store = RunStore(tmp_path)
    store.initialize({"model": "v1"})
    with pytest.raises(RuntimeError, match="controller"):
        RunStore(tmp_path)
    store.close()
    resumed = RunStore(tmp_path)
    resumed.initialize({"model": "v1"})
    with pytest.raises(ValueError, match="changed"):
        resumed.initialize({"model": "v2"})
    resumed.close()


def test_upstream_component_contract_real_mutation(tmp_path):
    from autosaddler.v2.core.ports import MutationContext
    from autosaddler.v2.harness.component_map import ComponentMapHarnessSpace

    from mm_harness.evolution.autosaddler import validate_components

    space = ComponentMapHarnessSpace(
        baseline={"harness.py": "def run(api):\n    return 1\n", "prompt.txt": "a"},
        store_root=tmp_path / "candidates",
        validator=validate_components,
    )
    parent = space.seed()
    mutation = space.begin_mutation(
        parent, MutationContext(0, "test", None, tmp_path / "mutations")
    )
    space.apply_updates(mutation, {"harness.py": "def run(api):\n    return 2\n"})
    child = space.finalize(mutation)
    assert parent.candidate_id != child.candidate_id
    assert child.parent_ids == (parent.candidate_id,)
    assert space.diff(parent, child).changed_units == ("harness.py",)


def test_candidate_prompt_is_loaded(tmp_path):
    from benchmarks.design2code.adapter import GenerationAPI

    harness = tmp_path / "h"
    harness.mkdir()
    (harness / "prompt.txt").write_text("actual candidate prompt")
    img = make_image(tmp_path / "ref.png")
    task = Task("x", "design2code", "exploration", "group", {"image": str(img)})
    api = GenerationAPI(
        {"placeholder": str(img)}, None, task, "child", 0, tmp_path / "run", harness
    )
    assert api.prompt == "actual candidate prompt"


def test_render_and_generation_share_code_digest(tmp_path, monkeypatch):
    from benchmarks.design2code.adapter import GenerationAPI

    from mm_harness.core.artifacts import read_json

    harness = tmp_path / "h"
    harness.mkdir()
    (harness / "prompt.txt").write_text("generate")
    img = make_image(tmp_path / "ref.png")
    config = {
        "placeholder": str(img),
        "max_model_calls": 1,
        "seed": 0,
        "browsers_path": "fixture",
        "node": "fixture",
        "renderer": "fixture",
        "driver": "fixture",
    }
    task = Task("x", "design2code", "exploration", "site", {"image": str(img)})
    client = model(
        lambda body: {
            **answer(body),
            "choices": [{"message": {"content": "<html><body>test</body></html>"}}],
        }
    )
    api = GenerationAPI(config, client, task, "child", 0, tmp_path / "run", harness)

    def render(command, **kwargs):
        make_image(Path(read_json(api.root / "render-0.json")[0]["outputPath"]))
        return {"returncode": 0}

    monkeypatch.setattr("benchmarks.design2code.adapter.run_process", render)
    api.render(api.generate(api.prompt, [api.reference_image]))
    events = api.trace.read()
    generation, render = events[-2:]
    assert generation["payload"]["code_sha256"] == render["payload"]["code_sha256"]

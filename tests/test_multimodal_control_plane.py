"""Research invariants, real file/hash operations and offline transport serialization."""

import base64
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.core.benchmarks import mechanism_profile, research_pool
from mm_harness.core.mechanisms import MechanismPatch, RuntimeTrigger, load_proposal
from mm_harness.core.media import crop_media
from mm_harness.core.media_artifacts import (
    MediaArtifact,
    MediaUse,
    derive_artifact,
    project_legacy_media,
    validate_artifact_graph,
)
from mm_harness.core.observability import MechanismRecorder, summarize_mechanisms
from mm_harness.core.store import Trace
from mm_harness.evolution.mutation_boundary import check_boundary
from mm_harness.evolution.rollout_workspace import build_rollout_workspace
from mm_harness.evolution.source_proposer import propose_source
from mm_harness.evolution.source_versions import snapshot
from mm_harness.runtimes.media_audit import audit_media_request

ROOT = Path(__file__).resolve().parents[1]


def mechanism(scope="generic", **changes):
    mm = scope == "multimodal_specific"
    values = dict(
        proposal_id="p1",
        scope=scope,
        primary_mm_stage="verify" if mm else None,
        secondary_mm_stages=[],
        modalities=["image"] if mm else [],
        failure_class="multimodal_harness" if mm else "generic_harness",
        failure_hypothesis="Result parser discarded the tool error"
        if not mm
        else "Stop uses old render",
        evidence_refs=["evidence/rollout-000#e00001"],
        media_evidence_refs=["image-1"] if mm else [],
        mechanism_description="Refresh render before stop"
        if mm
        else "Parse tool error before recovery",
        why_generic_or_multimodal="Requires current rendered pixels"
        if mm
        else "Semantics survive removing all pixels",
        media_dependency="Current render revision and pixels" if mm else None,
        expected_runtime_trigger=RuntimeTrigger(
            "mechanism_behavior", "before stop render inspection", {"stage": "verify"}
        )
        if mm
        else RuntimeTrigger("parse_recovery", "On malformed tool return, emit recovery"),
        expected_behavior_change="A performs the stated check before continuing",
        implementation_targets=["runtime.py"],
        budget_effect="Within fixed cap",
        invariants=["model/provider/budget/evaluator fixed"],
        risk_or_possible_regression="Extra calls may consume budget",
    )
    return MechanismPatch(**{**values, **changes})


def original(tmp_path):
    Image.new("RGB", (16, 12), "red").save(tmp_path / "original.png")
    return MediaArtifact.from_file(
        tmp_path,
        "original.png",
        modality="image",
        source_event_id="capture-1",
        source_tool_call_id="tool-1",
        created_step=2,
        freshness_state="fresh",
        metadata={"width": 16, "height": 12},
        provenance={"revision": "a"},
    )


def test_original_crop_frame_provenance_and_content_hash(tmp_path):
    artifact = original(tmp_path)
    assert artifact.verify_content(tmp_path) and artifact.created_step == 2
    (tmp_path / "media").mkdir()
    cropped = crop_media(
        tmp_path,
        {"path": artifact.storage_ref, "sha256": artifact.content_hash, "role": "observation"},
        (1, 2, 5, 6),
    )
    crop = derive_artifact(
        tmp_path,
        cropped["path"],
        parents=[artifact],
        transform={"operation": "crop", "box": [1, 2, 5, 6]},
        source_event_id="crop-1",
    )
    assert crop.parent_artifact_ids == [artifact.artifact_id]
    assert crop.content_hash != artifact.content_hash and crop.verify_content(tmp_path)
    # Frame lineage doesn't require running ffmpeg here: test output material from a fake extractor.
    (tmp_path / "video.mp4").write_bytes(b"synthetic video fixture")
    video = MediaArtifact.from_file(
        tmp_path,
        "video.mp4",
        modality="video",
        source_event_id="video-1",
        metadata={"duration_seconds": 2},
    )
    frame = derive_artifact(
        tmp_path,
        cropped["path"],
        parents=[video],
        transform={"operation": "frame", "timestamp_seconds": 1},
        source_event_id="frame-1",
    )
    catalog = validate_artifact_graph([artifact, crop, video, frame])
    assert catalog[frame.parent_artifact_ids[0]].modality == "video"
    with pytest.raises(ValueError, match="Missing parent"):
        validate_artifact_graph([crop])
    (tmp_path / "original.png").write_bytes(b"altered")
    assert not artifact.verify_content(tmp_path)
    with pytest.raises(ValueError, match="verified original"):
        derive_artifact(
            tmp_path,
            cropped["path"],
            parents=[artifact],
            transform={"operation": "crop"},
            source_event_id="crop-2",
        )


def test_same_pixels_new_observation_identity_and_freshness(tmp_path):
    a = original(tmp_path)
    b = MediaArtifact.from_file(
        tmp_path, "original.png", modality="image", source_event_id="capture-2"
    )
    assert a.content_hash == b.content_hash and a.artifact_id != b.artifact_id
    stale = replace(a, freshness_state="stale")
    assert a.freshness_state == "fresh" and stale.freshness_state == "stale"
    with pytest.raises(ValueError, match="SHA256"):
        replace(a, content_hash="bogus")


def test_legacy_projection_does_not_guess_ambiguous_parent():
    refs = [
        {"path": "a.png", "sha256": "a" * 64, "event_id": "a"},
        {"path": "b.png", "sha256": "a" * 64, "event_id": "b"},
        {
            "path": "crop.png",
            "sha256": "b" * 64,
            "source_sha256": "a" * 64,
            "event_id": "c",
            "crop_xyxy": [0, 0, 1, 1],
        },
    ]
    assert not project_legacy_media(refs, namespace="test")[-1].parent_artifact_ids
    projected = project_legacy_media([refs[0], refs[2]], namespace="test")
    assert projected[-1].parent_artifact_ids == [projected[0].artifact_id]


def test_generic_and_multimodal_proposals_are_orthogonal():
    assert mechanism().mm_stages == []
    spec = mechanism("multimodal_specific")
    assert MechanismPatch.from_dict(spec.to_dict()) == spec
    with pytest.raises(ValueError, match="Generic"):
        mechanism(primary_mm_stage="acquire")
    with pytest.raises(ValueError, match="Generic"):
        mechanism(media_dependency="pixels")


@pytest.mark.parametrize(
    "changes",
    [
        {"primary_mm_stage": None},
        {"media_dependency": None},
        {"media_evidence_refs": []},
        {"modalities": []},
        {"failure_class": "model_capability"},
    ],
)
def test_mm_proposal_requires_stage_media_and_harness_diagnosis(changes):
    with pytest.raises(ValueError):
        mechanism("multimodal_specific", **changes)


def test_score_is_not_runtime_trigger_and_legacy_is_not_reclassified():
    with pytest.raises(ValueError, match="not a score"):
        RuntimeTrigger("score", "improve score")
    old = {"mechanism_category": "visual_observation", "evidence": ["image.png"]}
    saved = copy.deepcopy(old)
    view = load_proposal(old)
    assert view["taxonomy"] == "legacy_taxonomy" and view["scope"] is None
    assert old == saved and view["raw"] == old


def test_artifact_exists_is_not_a_model_use_and_fresh_stale_are_auditable(tmp_path):
    artifact = original(tmp_path)
    trace = Trace(tmp_path / "trace", "task", "h")
    recorder = MechanismRecorder(trace)
    recorder.artifact(artifact)
    report = summarize_mechanisms(trace.read())
    assert report["counts"]["media_acquisitions"] == 1
    assert report["counts"]["fresh_artifacts_routed"] == 0
    assert report["counts_are_lower_bounds"]
    use = MediaUse(
        "u1",
        artifact.artifact_id,
        "req1",
        "A",
        "pixels",
        "inspect current state",
        "route",
        "fresh",
        True,
        True,
        transport_evidence="request/1+response/1",
    )
    recorder.use(use)
    recorder.use(
        replace(use, use_id="u2", request_id="req2", freshness_state="stale", revisit=True)
    )
    report = summarize_mechanisms(trace.read())
    assert report["counts"]["fresh_artifacts_routed"] == 1
    assert report["counts"]["stale_artifacts_routed"] == 1
    assert report["counts"]["media_revisits"] == 1
    with pytest.raises(ValueError, match="transport"):
        replace(use, transport_evidence=None)
    with pytest.raises(ValueError, match="understanding"):
        replace(use, understood_correctly=True)


def test_trigger_states_do_not_follow_diff_or_other_candidate_or_evaluator(tmp_path):
    spec = mechanism("multimodal_specific")
    trace = Trace(tmp_path, "task", "h")
    recorder = MechanismRecorder(trace)
    assert (
        summarize_mechanisms([], proposal=spec, implemented=True)["trigger_status"]
        == "trigger_unknown"
    )
    assert (
        summarize_mechanisms([], proposal=spec, coverage_complete=True)["trigger_status"]
        == "not_triggered"
    )
    recorder.behavior("verify", artifact_ids=["image-1"], mechanism_id="other")
    trace.add("evaluation", stage="verify", role="evaluator", uses_vlm=True)
    assert summarize_mechanisms(trace.read(), proposal=spec)["trigger_status"] == "trigger_unknown"
    recorder.behavior("verify", artifact_ids=["image-1"], mechanism_id=spec.proposal_id)
    assert summarize_mechanisms(trace.read(), proposal=spec)["trigger_status"] == "triggered"
    assert (
        summarize_mechanisms(trace.read(), role="B")["counts"]["multimodal_verification_events"]
        == 0
    )


def test_transport_audit_actual_bytes_not_quoted_text_or_token_count(tmp_path):
    encoded = base64.b64encode(b"pixel fixture").decode()
    url = f"data:image/png;base64,{encoded}"
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": url},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
    }
    audit_media_request(body, tmp_path, role="A", transport_status=200)
    audit = read_json(tmp_path / "media-audit.json")
    assert len(audit["artifacts"]) == 1
    assert audit["uses"][0]["passed_to_model"] is True
    assert audit["uses"][0]["freshness_state"] == "unknown"
    assert MediaArtifact(**audit["artifacts"][0]).verify_content(tmp_path)
    audit_media_request(body, tmp_path, role="B", transport_status=200, generation=False)
    assert read_json(tmp_path / "media-audit.json")["uses"][0]["passed_to_model"] is False
    audit_media_request(body, tmp_path, role="A", transport_status="network_error")
    assert read_json(tmp_path / "media-audit.json")["uses"][0]["passed_to_model"] is None


def test_registry_six_active_two_archived_no_status_inflation():
    assert {p.benchmark_id for p in research_pool()} == {
        "swe_mm",
        "gamedevbench",
        "vision2web",
        "osworld_verified",
        "agentic_vbench",
        "browsecomp_v3",
    }
    assert len(research_pool(status="all")) == 8
    for name in ("design2code", "claw_eval_mm"):
        assert mechanism_profile(name).status == "archived"
    for name in ("chartmimic", "visualwebarena"):
        with pytest.raises(ValueError, match="removed"):
            mechanism_profile(name)
    for name in ("agentic_vbench", "browsecomp_v3", "vision2web"):
        assert mechanism_profile(name).integration_status == "source_integrated"
    for name in ("gamedevbench", "osworld_verified"):
        assert mechanism_profile(name).integration_status == "planned"
    swe = mechanism_profile("swe_mm")
    assert swe.known_mm_failure_evidence == [] and swe.mechanism_headroom == "unknown"
    with pytest.raises(ValueError, match="real MM failure"):
        replace(swe, mechanism_headroom="confirmed")


@pytest.mark.parametrize(
    "path",
    [
        "scorer/judge.py",
        "evaluator/score.py",
        "ground_truth/answer.txt",
        "hidden_answers/a.txt",
        "models.py",
        "providers/config.py",
        "sweagent/agent/models.py",
        "sweagent/environment/runtime.py",
    ],
)
def test_fixed_boundary_overrides_broad_allowlist(tmp_path, path):
    parent, child = tmp_path / "parent", tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    p = child / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x=1\n")
    policy = read_json(ROOT / "benchmarks/swe_mm/mutation-boundary.json")
    policy["mutable"] = [{"path": "**", "scopes": ["generic"], "mm_stages": []}]
    result = check_boundary(parent, child, policy, mechanism(implementation_targets=[path]))
    assert not result["valid"] and any("Fixed boundary" in e for e in result["errors"])


def test_yaml_model_and_budget_cannot_change(tmp_path):
    policy = read_json(ROOT / "benchmarks/swe_mm/mutation-boundary.json")
    name = "config/default_mm_with_images.yaml"
    original_yaml = ROOT / "third_party/SWE-agent-3ea751c087f32b16e039a2233dd6eefecef325d5" / name
    if not original_yaml.exists():
        pytest.skip("Restore pinned SWE source for source-level contract")
    import yaml

    parent, child = tmp_path / "p", tmp_path / "c"
    for root in [parent, child]:
        (root / name).parent.mkdir(parents=True)
        (root / name).write_bytes(original_yaml.read_bytes())
    value = yaml.safe_load((child / name).read_text())
    value["agent"]["model"] = {"name": "different-model", "per_instance_cost_limit": 999}
    (child / name).write_text(yaml.safe_dump(value))
    assert not check_boundary(parent, child, policy, mechanism(implementation_targets=[name]))[
        "valid"
    ]


def test_modern_workspace_and_proposer_bind_real_patch_identity(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "runtime.py").write_text("def parse():\n    return 'old'\n")
    parent = tmp_path / "parent"
    version = snapshot(source, parent)
    rollout = tmp_path / "rollout"
    trace = Trace(rollout, "task", version["id"])
    trace.add("tool_step", action="parse", observation="malformed")
    outcome = {
        "task_id": "task",
        "harness_id": version["id"],
        "split": "exploration",
        "rollout": str(rollout),
        "score": 0,
        "status": "task_failure",
    }
    write_json(
        tmp_path / "boundary.json",
        {
            "schema": 3,
            "mutable": [{"path": "runtime.py", "scopes": ["generic"], "mm_stages": []}],
            "fixed": {},
        },
    )

    def fake_b(root, workspace, role, base_url, output):
        assert read_json(workspace / "media-catalog.json")["event_refs"] == [
            "evidence/rollout-000#e00001"
        ]
        write_json(
            workspace / "diagnosis.json",
            {
                "diagnosis_id": "d",
                "parent_harness_id": version["id"],
                "failure_class": "generic_harness",
                "reason": "Actual malformed tool output; repair hypothesis",
                "source_checks": [
                    {"path": "runtime.py", "symbol": "parse", "finding": "Returns old placeholder"}
                ],
            },
        )
        (workspace / "source/runtime.py").write_text("def parse():\n    return 'new'\n")
        write_json(
            workspace / "proposal.json",
            {"status": "candidate", "diagnosis_id": "d", "mechanism_patch": mechanism().to_dict()},
        )

    monkeypatch.setattr("mm_harness.evolution.source_proposer.run_claude", fake_b)
    result = propose_source(
        root=tmp_path,
        parent=parent,
        outcomes=[outcome],
        output=tmp_path / "proposal",
        config={
            "evidence_mode": "multimodal",
            "proposal_schema": "mechanism-patch/v1",
            "mutation_policy": "boundary.json",
        },
        role={},
        base_url="unused",
    )
    assert result["status"] == "candidate"
    spec = MechanismPatch.from_dict(read_json(Path(result["mechanism_patch"])))
    assert spec.frozen_candidate_identity == result["harness_id"] != version["id"]
    assert result["mechanism_status"]["trigger_status"] == "trigger_unknown"
    assert (parent / "source/runtime.py").read_text().endswith("'old'\n")


def test_canonical_workspace_keeps_media_use_parent_and_text_ablation(tmp_path):
    root = tmp_path / "rollout"
    root.mkdir()
    a = original(root)
    trace = Trace(root, "task", "h")
    recorder = MechanismRecorder(trace)
    recorder.artifact(a)
    use = MediaUse(
        "u",
        a.artifact_id,
        "req",
        "A",
        "pixels",
        "observe",
        "route",
        "fresh",
        True,
        True,
        transport_evidence="raw request + response",
    )
    recorder.use(use)
    before = trace.path.read_bytes()
    for mode in ("text", "multimodal"):
        workspace = tmp_path / mode
        overview = build_rollout_workspace(
            [
                {
                    "task_id": "task",
                    "harness_id": "h",
                    "split": "exploration",
                    "rollout": str(root),
                    "score": 0,
                    "status": "task_failure",
                }
            ],
            parent_id="h",
            workspace=workspace,
            mode=mode,
            allowed_edits=[],
            canonical_media=True,
        )
        artifacts = read_json(workspace / overview["outcomes"][0]["media_artifacts"])
        assert artifacts[0]["artifact_id"] == a.artifact_id
        assert artifacts[0]["freshness_state"] == "fresh"
        assert (
            read_json(workspace / overview["outcomes"][0]["media_uses"])[0]["artifact_id"]
            == a.artifact_id
        )
        assert (artifacts[0]["storage_ref"] is not None) == (mode == "multimodal")
    assert trace.path.read_bytes() == before


def test_legacy_media_identity_is_stable_across_evidence_conditions():
    raw = {"sha256": "f" * 64, "event_id": "e1", "path": "evidence/rollout-000/media/f.png"}
    text = {**raw, "path": None}
    a = project_legacy_media([raw], namespace="task:parent:sample:eventhash")[0]
    b = project_legacy_media([text], namespace="task:parent:sample:eventhash")[0]
    other = project_legacy_media([raw], namespace="other_task:parent:sample:eventhash")[0]
    assert a.artifact_id == b.artifact_id != other.artifact_id


def test_valid_yaml_template_change_uses_new_boundary(tmp_path):
    import yaml

    policy = read_json(ROOT / "benchmarks/swe_mm/mutation-boundary.json")
    name = "config/default_mm_with_images.yaml"
    source = ROOT / "third_party/SWE-agent-3ea751c087f32b16e039a2233dd6eefecef325d5" / name
    if not source.exists():
        pytest.skip("Restore SWE source")
    parent, candidate = tmp_path / "p", tmp_path / "c"
    for directory in [parent, candidate]:
        (directory / name).parent.mkdir(parents=True)
        (directory / name).write_bytes(source.read_bytes())
    value = yaml.safe_load(source.read_text())
    value["agent"]["templates"]["system_template"] += " Keep tool errors visible."
    (candidate / name).write_text(yaml.safe_dump(value))
    assert check_boundary(parent, candidate, policy, mechanism(implementation_targets=[name]))[
        "valid"
    ]


def test_mm_proposal_fabricated_media_is_rejected(tmp_path):
    from mm_harness.evolution.mechanism_review import review_mechanism

    workspace, parent = tmp_path / "workspace", tmp_path / "parent"
    for directory in [workspace, parent]:
        (directory / "source").mkdir(parents=True)
        (directory / "source/runtime.py").write_text("x=1\n")
    (workspace / "source/runtime.py").write_text("x=2\n")
    write_json(
        workspace / "media-catalog.json",
        {
            "artifact_ids": [],
            "event_refs": ["evidence/rollout-000#e00001"],
            "artifact_event_refs": {},
        },
    )
    result = review_mechanism(
        workspace,
        parent,
        {
            "status": "candidate",
            "diagnosis_id": "d",
            "mechanism_patch": mechanism("multimodal_specific").to_dict(),
        },
        {
            "diagnosis_id": "d",
            "parent_harness_id": "h",
            "failure_class": "multimodal_harness",
            "reason": "Claim pixels",
            "source_checks": [{"path": "runtime.py", "symbol": "x", "finding": "placeholder"}],
        },
        {
            "mutable": [
                {"path": "runtime.py", "scopes": ["multimodal_specific"], "mm_stages": ["verify"]}
            ],
            "fixed": {},
        },
        "h",
    )
    assert not result["valid"] and "Unresolved media evidence references" in result["errors"]


def test_modern_no_change_for_insufficient_evidence(tmp_path):
    from mm_harness.evolution.mechanism_review import review_mechanism

    result = review_mechanism(
        tmp_path,
        tmp_path,
        {"status": "no_change", "diagnosis_id": "d"},
        {
            "diagnosis_id": "d",
            "parent_harness_id": "h",
            "failure_class": "insufficient_evidence",
            "reason": "No actual media/state mapping; cannot diagnose staleness",
        },
        {},
        "h",
    )
    assert result["valid"] and result["mechanism"] is None


def test_swe_export_reuses_canonical_request_identity_without_double_counting(tmp_path):
    from benchmarks.swe_mm.cluster_runner import export

    call = tmp_path / "attempt/rollout/requests/call-0000"
    call.mkdir(parents=True)
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
                ],
            }
        ]
    }
    write_json(call / "request.json", body)
    (call / "response.raw").write_text(json.dumps({"choices": [], "usage": {}}))
    audit_media_request(body, call, role="A", transport_status=200)
    outcome = export(
        {"task_id": "t", "harness_id": "h", "split": "exploration", "sample": 0},
        tmp_path / "attempt",
        {"seconds": 0},
        {"resolved": False},
    )
    workspace = tmp_path / "workspace"
    overview = build_rollout_workspace(
        [outcome],
        parent_id="h",
        workspace=workspace,
        mode="multimodal",
        allowed_edits=[],
        canonical_media=True,
    )
    artifacts = read_json(workspace / overview["outcomes"][0]["media_artifacts"])
    uses = read_json(workspace / overview["outcomes"][0]["media_uses"])
    assert len(artifacts) == len(uses) == 1
    assert artifacts[0]["artifact_id"] == uses[0]["artifact_id"]
    assert uses[0]["passed_to_model"] is True
    assert MediaArtifact(**artifacts[0]).verify_content(workspace)

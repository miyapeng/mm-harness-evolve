"""Connect exploration event records, Claude Code edits and frozen source versions."""

from __future__ import annotations

import shutil
from pathlib import Path

from mm_harness.core.artifacts import digest, read_json, tree_manifest, write_json
from mm_harness.evolution.history import build_history_workspace, verify_history
from mm_harness.evolution.mutation_policy import allowed_files, check_policy, resolve_policy
from mm_harness.evolution.rollout_workspace import build_rollout_workspace
from mm_harness.evolution.source_versions import review, snapshot, verify
from mm_harness.runtimes.claude_code import run_claude


def propose_source(
    *,
    root: Path,
    parent: Path,
    outcomes: list[dict],
    output: Path,
    config: dict,
    role: dict,
    base_url: str,
    history: list[dict] | None = None,
) -> dict:
    """Consume normalized rollout/events.jsonl records; never scorer-private inputs."""
    policy = resolve_policy(root, config)
    modern = config.get("proposal_schema") == "mechanism-patch/v1"
    if modern and (policy is None or policy.get("schema") != 3):
        raise ValueError("MechanismPatch requires a stage/source boundary schema 3")
    history = history or []
    for entry in history:
        verify_history(entry, config["evidence_mode"])
    if config.get("benchmark") == "swe_mm" and policy is None:
        raise ValueError("SWE pilot requires an explicit mutation policy")
    actor = read_json(root / config["model_roles"])["actor"] if config.get("model_roles") else {}
    fixed_context = {
        "benchmark": config.get("benchmark"),
        "h0": config.get("actor_h0"),
        "executor": {
            k: actor[k]
            for k in (
                "model",
                "temperature",
                "top_p",
                "max_tokens",
                "max_requests",
                "wall_timeout_seconds",
            )
            if k in actor
        },
        "evolver_model": role.get("model"),
        "evolver_budget": {
            **{
                k: role[k]
                for k in ("max_requests", "max_turns", "max_tokens", "wall_timeout_seconds")
                if k in role
            },
            "accounting": "Request cap includes Claude Code auxiliary calls; reserve calls for diagnosis, edits and proposal. Use indexes and concise excerpts before opening complete traces.",
        },
        "evidence_mode": config["evidence_mode"],
        "batch_size": config.get("evolution_batch_size"),
        "validation_batch_size": config.get("validation_batch_size"),
        "selection": {k: config[k] for k in ("batch_gate", "dev_gate") if k in config},
        "goal": "Improve future task execution through one reusable mechanism; no task solutions",
        "missing_evidence": "Do not infer A's input or screenshot freshness from absent records",
    }
    input_id = digest(
        {
            "workspace_schema": 5 if modern else 4,
            "parent": verify(parent)["id"],
            "outcomes": outcomes,
            "config": config,
            "role": role,
            "policy": policy,
            "fixed_context": fixed_context,
            "history": history,
        }
    )
    if (output / "result.json").exists():
        result = read_json(output / "result.json")
        if result["input_id"] != input_id:
            raise ValueError("Cached proposal has different evidence, configuration or parent")
        return result
    if any(r["split"] != "exploration" for r in outcomes):
        raise ValueError("Only exploration trajectories may enter diagnosis")
    parent_id = verify(parent)["id"]
    if any(r["harness_id"] != parent_id for r in outcomes):
        raise ValueError("Evidence must identify the current parent harness")
    workspace = output / "workspace"
    if workspace.exists():
        raise RuntimeError(
            "Interrupted proposal retained; inspect it and use a new attempt directory"
        )
    shutil.copytree(parent / "source", workspace / "source")
    allowed = allowed_files(policy) if policy else config["mutation_surface"]
    if policy and "mutation_surface" in config and config["mutation_surface"] != allowed:
        raise ValueError("Mutation file list differs from the explicit policy")
    overview = build_rollout_workspace(
        outcomes,
        parent_id=parent_id,
        workspace=workspace,
        mode=config["evidence_mode"],
        allowed_edits=allowed,
        canonical_media=modern,
    )
    overview.update(
        build_history_workspace(history, workspace=workspace, mode=config["evidence_mode"])
    )
    with (workspace / "WORKSPACE.md").open("a") as stream:
        stream.write(
            "\nRead history/index.json for previous attempts, including rejections. "
            "History is read-only; source/ remains the selected parent's candidate copy.\n"
        )
    write_json(workspace / "experiment-context.json", fixed_context)
    if policy:
        write_json(workspace / "mutation-policy.json", policy)
        overview.update(
            mutation_policy="mutation-policy.json", experiment_context="experiment-context.json"
        )
    write_json(workspace / "overview.json", overview)
    write_json(output / "input.json", overview)
    run_claude(root, workspace, role, base_url, output / "claude")
    if tree_manifest(workspace / "evidence") != read_json(workspace / "evidence-manifest.json"):
        raise ValueError("Evidence workspace changed during proposal")
    if tree_manifest(workspace / "history") != read_json(workspace / "history-manifest.json"):
        raise ValueError("History workspace changed during proposal")
    proposal = read_json(workspace / "proposal.json")
    diagnosis_path = workspace / "diagnosis.json"
    diagnosis = read_json(diagnosis_path) if diagnosis_path.exists() else None
    diagnosis_valid = bool(
        isinstance(diagnosis, dict)
        and diagnosis.get("diagnosis_id")
        and diagnosis.get("parent_harness_id") == parent_id
        and diagnosis.get("problem")
        and diagnosis.get("hypothesis")
        and diagnosis.get("evidence_refs")
        and diagnosis.get("mechanism_check")
        and proposal.get("diagnosis_id") == diagnosis.get("diagnosis_id")
    )
    report = review(parent, workspace / "source", allowed=allowed)
    mechanism_report = None
    if modern:
        from mm_harness.evolution.mechanism_review import review_mechanism

        mechanism_report = review_mechanism(
            workspace, parent, proposal, diagnosis, policy, parent_id
        )
        diagnosis_valid = mechanism_report["valid"]
        report["mechanism"] = mechanism_report
        report["errors"].extend(mechanism_report["errors"])
        report["valid"] = report["valid"] and mechanism_report["valid"]
    if not modern and policy and proposal.get("status") == "candidate":
        category = diagnosis.get("mechanism_category") if isinstance(diagnosis, dict) else None
        policy_report = check_policy(
            parent / "source", workspace / "source", policy, category, proposal.get("change_map")
        )
        if proposal.get("mechanism_category") != category:
            policy_report["errors"].append("Diagnosis/proposal mechanism category differs")
            policy_report["valid"] = False
        report["policy"] = policy_report
        report["errors"].extend(policy_report["errors"])
        report["valid"] = report["valid"] and policy_report["valid"]
    write_json(output / "review.json", {k: v for k, v in report.items() if k != "patch"})
    (output / "harness.patch").write_text(report["patch"])
    status = proposal.get("status")
    if (
        status not in {"no_change", "candidate"}
        or not report["valid"]
        or (status == "candidate" and not diagnosis_valid)
    ):
        status = "invalid"
    elif status == "no_change" and report["changed"]:
        status = "invalid"
    elif not report["changed"]:
        status = "no_change"
    result = {
        "input_id": input_id,
        "status": status,
        "parent": parent_id,
        "proposal": proposal,
        "diagnosis": diagnosis,
        "diagnosis_valid": diagnosis_valid,
        "evidence_manifest": read_json(workspace / "evidence-manifest.json"),
        "history": history,
        "cost": read_json(output / "claude/usage.json")
        if (output / "claude/usage.json").exists()
        else None,
        "review": str(output / "review.json"),
        "patch": str(output / "harness.patch"),
    }
    if status == "candidate":
        version = snapshot(workspace / "source", output / "version", parent=parent_id)
        result.update(harness_id=version["id"], version_dir=str(output / "version"))
    if modern:
        result["proposal_schema"] = "mechanism-patch/v1"
        result["mechanism_status"] = {
            "implemented": status == "candidate",
            "trigger_status": "trigger_unknown",
        }
        if status == "candidate":
            spec = dict(mechanism_report["mechanism"])
            spec.update(source_diff="harness.patch", frozen_candidate_identity=result["harness_id"])
            write_json(output / "mechanism-patch.json", spec)
            result["mechanism_patch"] = str(output / "mechanism-patch.json")
    write_json(output / "result.json", result)
    return result

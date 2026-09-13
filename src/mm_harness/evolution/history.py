"""Immutable, model-readable round archives, with exploration-only raw evidence."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from mm_harness.core.artifacts import digest, read_json, tree_manifest, write_json
from mm_harness.evolution.rollout_workspace import build_rollout_workspace
from mm_harness.evolution.source_versions import verify


def verify_history(entry: dict, mode: str) -> Path:
    directory = Path(entry["directory"])
    if entry["mode"] != mode or read_json(directory / "record.json")["mode"] != mode:
        raise ValueError("History evidence mode differs; do not mix ablation conditions")
    if digest(tree_manifest(directory)) != entry["id"]:
        raise ValueError("Historical archive changed after freezing")
    return directory


def _costs(rows: list[dict]) -> dict:
    totals, observations = {}, {}
    for row in rows:
        for key, value in (row.get("cost") or {}).items():
            if type(value) in {int, float}:
                totals[key] = totals.get(key, 0) + value
                observations[key] = observations.get(key, 0) + 1
    return {"rollouts": len(rows), "totals": totals, "observed_rollouts": observations}


def archive_round(
    directory: Path,
    *,
    state: dict,
    parent_version: Path,
    mode: str,
    round_index: int,
) -> dict:
    """Export only approved evidence; V raw records remain in the controller's round.json."""
    source_id = digest(state)
    if directory.exists():
        manifest = read_json(directory / "record.json")
        if manifest["source_round_digest"] != source_id or manifest["mode"] != mode:
            raise ValueError("Existing history belongs to a different round")
        return {
            "directory": str(directory.resolve()),
            "id": digest(tree_manifest(directory)),
            "mode": mode,
            "round_index": round_index,
        }
    parent_id = verify(parent_version)["id"]
    if parent_id != state["spec"]["parent"]:
        raise ValueError("History parent source differs from the measured version")
    proposal = state.get("proposal", {})
    rows = list(state["attempts"].values())
    e_rows = [r for r in rows if r["split"] == "exploration"]
    v_rows = [r for r in rows if r["split"] == "validation"]
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".archive-", dir=directory.parent) as temporary:
        work = Path(temporary) / "archive"
        work.mkdir()
        shutil.copytree(parent_version, work / "parent")
        candidate_id = proposal.get("harness_id")
        if proposal.get("version_dir"):
            version = Path(proposal["version_dir"])
            record = verify(version)
            if record["id"] != candidate_id or record["parent"] != parent_id:
                raise ValueError("History candidate source/parent mismatch")
            shutil.copytree(version, work / "candidate")
        groups = {}
        unavailable = []
        for name, harness_id in (("parent", parent_id), ("candidate", candidate_id)):
            selected = [r for r in e_rows if r["harness_id"] == harness_id]
            missing = [r for r in selected if not r.get("rollout")]
            if any(r["status"] in {"success", "task_failure"} for r in missing):
                raise ValueError("Completed exploration outcome must export a rollout")
            unavailable.extend(
                {k: r[k] for k in ("task_id", "harness_id", "status")} for r in missing
            )
            selected = [r for r in selected if r.get("rollout")]
            if selected:
                build_rollout_workspace(
                    selected,
                    parent_id=harness_id,
                    workspace=work / f"{name}-rollouts",
                    mode=mode,
                    allowed_edits=[],
                    canonical_media=proposal.get("proposal_schema") == "mechanism-patch/v1",
                )
                groups[name] = f"{name}-rollouts/overview.json"
        if proposal.get("patch"):
            shutil.copyfile(proposal["patch"], work / "harness.patch")
        write_json(work / "diagnosis.json", proposal.get("diagnosis"))
        write_json(work / "proposal.json", proposal.get("proposal", {}))
        if proposal.get("mechanism_patch"):
            write_json(work / "mechanism-patch.json", read_json(Path(proposal["mechanism_patch"])))
        if state.get("mechanism_observations"):
            write_json(
                work / "mechanism-observations.json",
                read_json(Path(state["mechanism_observations"])),
            )
        # Deliberately not copying proposal/workspace, native scorer trees, or round.json.
        if proposal.get("review"):
            write_json(work / "review.json", read_json(Path(proposal["review"])))
        record = {
            "schema": 1,
            "round_index": round_index,
            "source_round_digest": source_id,
            "mode": mode,
            "parent": parent_id,
            "candidate": candidate_id,
            "selected": state.get("selected", parent_id),
            "status": state["status"],
            "exploration_comparison": state.get("batch_comparison"),
            "validation_summary": {
                k: v
                for k, v in state.get("dev_comparison", {}).items()
                if k in {"status", "passed", "gain", "parent_mean", "candidate_mean", "reason"}
            },
            "costs": {
                "exploration": _costs(e_rows),
                "validation": _costs(v_rows),
                "evolver": proposal.get("cost"),
            },
            "sources": {
                "parent": "parent/source",
                "candidate": "candidate/source" if (work / "candidate").exists() else None,
            },
            "evidence": groups,
            "patch": "harness.patch" if proposal.get("patch") else None,
            "unavailable_exploration_evidence": unavailable,
            "diagnosis": "diagnosis.json",
            "proposal": "proposal.json",
            **(
                {"mechanism_patch": "mechanism-patch.json"}
                if proposal.get("mechanism_patch")
                else {}
            ),
            **(
                {"mechanism_observations": "mechanism-observations.json"}
                if state.get("mechanism_observations")
                else {}
            ),
            "interpretation": "Scores are measured; B's diagnosis is a hypothesis, not a verified cause.",
        }
        write_json(work / "record.json", record)
        (work / "README.md").write_text(
            "Read record.json for selection and per-task E gains. All paths are relative to this "
            "round directory. Each *-rollouts/ directory is a separate evidence workspace: "
            "prefix its paths with that directory when using Read. Sources belong to their "
            "recorded versions; historical images may be stale for the current parent. "
            "V summary is selection feedback; V/T raw traces and answers are unavailable.\n"
        )
        work.rename(directory)
    return {
        "directory": str(directory.resolve()),
        "id": digest(tree_manifest(directory)),
        "mode": mode,
        "round_index": round_index,
    }


def build_history_workspace(entries: list[dict], *, workspace: Path, mode: str) -> dict:
    history = workspace / "history"
    history.mkdir(parents=True)
    index = []
    for entry in entries:
        source = verify_history(entry, mode)
        name = f"round-{entry['round_index']:03}"
        shutil.copytree(source, history / name)
        record = read_json(source / "record.json")
        index.append(
            {k: record[k] for k in ("round_index", "parent", "candidate", "selected", "status")}
            | {"directory": name, "record": f"{name}/record.json", "archive_id": entry["id"]}
        )
    write_json(
        history / "index.json",
        {"rounds": index, "mode": mode, "path_base": "history/", "raw_splits": ["exploration"]},
    )
    write_json(workspace / "history-manifest.json", tree_manifest(history))
    return {
        "history_available": bool(entries),
        "history_index": "history/index.json",
        "history_rounds": len(entries),
    }

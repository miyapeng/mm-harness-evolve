"""Sequential source-harness search with explicit E/V gates and queryable history."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from mm_harness.core.artifacts import digest, read_json, write_json
from mm_harness.evolution.history import archive_round, verify_history
from mm_harness.evolution.minibatch import run_configured_round
from mm_harness.evolution.mutation_policy import resolve_policy
from mm_harness.evolution.source_proposer import propose_source
from mm_harness.evolution.source_versions import verify


def _project(directory: Path, state: dict) -> None:
    nodes = [{"id": "H0", "harness_id": state["spec"]["h0"], "status": "seed"}]
    edges = []
    lines = [
        "# Search history",
        "",
        f"Model: `{state['spec']['model_id']}`. "
        f"Configuration: `{state['spec']['config'].get('status', 'unspecified')}`.",
        "",
        "```mermaid",
        "flowchart LR",
        '  H0["H0"]',
    ]
    for row in state["rounds"]:
        name = f"attempt{row['round_index']}"
        nodes.append({"id": name, "harness_id": row["candidate"], "status": row["status"]})
        edges.append({"parent": row["parent_node"], "child": name, "kind": "attempt_from"})
        lines.append(
            f'  {row["parent_node"]} --> {name}["Round {row["round_index"]}: {row["status"]}"]'
        )
    lines += [
        "```",
        "",
        "Nodes identify attempts; identical code hashes can recur without creating cycles.",
        "No history reading is counted as code inheritance. No multi-parent merge is enabled.",
        "",
        "| Round | Status | E gain | V gain | Record |",
        "|---|---|---|---|---|",
    ]
    for row in state["rounds"]:
        record = read_json(Path(row["archive"]["directory"]) / "record.json")
        e_gain = (record["exploration_comparison"] or {}).get("gain", "—")
        v_gain = record["validation_summary"].get("gain", "—")
        path = f"history/round-{row['round_index']:03}/record.json"
        lines.append(
            f"| {row['round_index']} | {row['status']} | {e_gain} | {v_gain} | [record]({path}) |"
        )
    lines += [
        "",
        "Gains are paired within each round. Different V batches are not a global ranking.",
    ]
    write_json(
        directory / "lineage.json",
        {"nodes": nodes, "edges": edges, "selected": state["selected_node"]},
    )
    (directory / "history.md").write_text("\n".join(lines) + "\n")
    if state["status"] == "complete":
        write_json(
            directory / "selection.json",
            {
                "harness_id": state["selected"],
                "version_dir": state["versions"][state["selected"]],
                "reason": "last accepted version under paired E>0 and V>=0 gates",
                "search_spec_id": digest(state["spec"]),
                "test_evaluated": False,
            },
        )


def run_search(
    *,
    root: Path,
    directory: Path,
    config: dict,
    split: dict,
    h0: Path,
    role: dict,
    base_url: str,
    protocol_id: str,
    model_id: str,
    runner: Callable,
    round_limit: int | None = None,
) -> dict:
    """Runner(identity, frozen_source_path, attempt_dir) owns fresh execution and official scoring.

    Pending propagates from the single-round controller; retry resumes finished stages.
    round_limit limits *additional* rounds in this invocation, without changing the experiment.
    """
    if config.get("search_strategy") != "current_parent_with_history":
        raise ValueError("Select current_parent_with_history explicitly")
    maximum = config["max_rounds"]
    if type(maximum) is not int or maximum < 1:
        raise ValueError("max_rounds must be positive")
    if round_limit is not None and (type(round_limit) is not int or round_limit < 1):
        raise ValueError("round_limit must be positive")
    role = dict(role)
    if "system_prompt" not in role and role.get("system_prompt_file"):
        role["system_prompt"] = (root / role["system_prompt_file"]).read_text()
    actor = read_json(root / config["model_roles"]) if config.get("model_roles") else None
    if actor and actor["actor"]["model"] != role["model"]:
        raise ValueError("Main search requires A=B")
    spec = {
        "schema": 1,
        "config": config,
        "split": split,
        "h0": verify(h0)["id"],
        "role": role,
        "model_roles": actor,
        "policy": resolve_policy(root, config),
        "protocol_id": protocol_id,
        "model_id": model_id,
    }
    state_path = directory / "search.json"
    if state_path.exists():
        state = read_json(state_path)
        if state["spec"] != spec:
            raise ValueError("Search resume configuration, model, policy or split differs")
    else:
        state = {
            "spec": spec,
            "status": "running",
            "rounds": [],
            "selected": spec["h0"],
            "selected_node": "H0",
            "versions": {spec["h0"]: str(h0.resolve())},
        }
        write_json(state_path, state)
    history = [r["archive"] for r in state["rounds"]]
    for entry in history:
        verify_history(entry, config["evidence_mode"])
    if state["status"] in {"complete", "inconclusive"}:
        _project(directory, state)
        return state
    stop = min(maximum, len(state["rounds"]) + (round_limit or maximum))
    for index in range(len(state["rounds"]), stop):
        round_dir = directory / "rounds" / f"round-{index:03}"
        parent_id, parent_node = state["selected"], state["selected_node"]

        def version_path(harness_id):
            if harness_id not in state["versions"]:
                # A resumed round may have finished B before search.json recorded its version.
                proposal = read_json(round_dir / "round.json")["proposal"]
                version = Path(proposal["version_dir"])
                actual = verify(version)
                if actual["id"] != harness_id or actual["parent"] != parent_id:
                    raise ValueError("Candidate version does not match the measured lineage")
                state["versions"][harness_id] = str(version.resolve())
            version = Path(state["versions"][harness_id])
            if verify(version)["id"] != harness_id:
                raise ValueError("Runner would load the wrong harness version")
            return version

        def measured(identity, attempt):
            version = version_path(identity["harness_id"])
            sampling_id = digest(
                {"search": str(directory.resolve()), "round_index": index, **identity}
            )
            execution_identity = {**identity, "round_index": index, "sampling_id": sampling_id}
            result = runner(execution_identity, version / "source", attempt)
            if any(result.get(k) != v for k, v in execution_identity.items()):
                raise ValueError("Runner returned a different sampling identity")
            verify(version)
            return result

        def propose(parent, outcomes, output):
            return propose_source(
                root=root,
                parent=version_path(parent),
                outcomes=outcomes,
                output=output,
                config=config,
                role=role,
                base_url=base_url,
                history=history,
            )

        result = run_configured_round(
            round_dir,
            config=config,
            split=split,
            round_index=index,
            parent=parent_id,
            protocol_id=protocol_id,
            model_id=model_id,
            runner=measured,
            proposer=propose,
        )
        entry = archive_round(
            directory / "history" / f"round-{index:03}",
            state=result,
            parent_version=version_path(parent_id),
            mode=config["evidence_mode"],
            round_index=index,
        )
        child_id = result.get("proposal", {}).get("harness_id")
        if child_id:
            version_path(child_id)
        state["rounds"].append(
            {
                "round_index": index,
                "parent": parent_id,
                "parent_node": parent_node,
                "candidate": child_id,
                "status": result["status"],
                "archive": entry,
            }
        )
        state["selected"] = result.get("selected", parent_id)
        if result["status"] == "accepted":
            state["selected_node"] = f"attempt{index}"
        history.append(entry)
        state["status"] = (
            "inconclusive"
            if result["status"] == "inconclusive"
            else "complete"
            if len(state["rounds"]) == maximum
            else "running"
        )
        write_json(state_path, state)
        _project(directory, state)
        if state["status"] == "inconclusive":
            break
    return state

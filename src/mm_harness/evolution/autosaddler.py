"""Scenario/provider/policy extensions of pinned AutoSaddler V2; no upstream edits."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import asdict
from pathlib import Path

from autosaddler.v2.core.domain import (
    ArtifactRef,
    Case,
    Cost,
    Evaluation,
    Observation,
    PatchVerdict,
    to_json_value,
)
from autosaddler.v2.core.ports import ScenarioComponents
from autosaddler.v2.harness.component_map import ComponentMapHarnessSpace
from autosaddler.v2.plugins.api import SCENARIO_PLUGIN_API_VERSION, ScenarioPlugin
from autosaddler.v2.prompting.models import SessionResult, SessionSpec, Usage

from mm_harness.core.artifacts import canonical, digest, read_json, tree_manifest, write_json
from mm_harness.core.benchmarks import adapter_for
from mm_harness.core.schema import Outcome, Task, validate_splits
from mm_harness.evolution.evidence import build_evidence
from mm_harness.evolution.proposer import propose
from mm_harness.evolution.selection import select
from mm_harness.runtimes.model import ChatModel, assert_same_model

SPLITS = {"train": "exploration", "development": "validation", "test": "test"}


def validate_components(files):
    if set(files) != {"harness.py", "prompt.txt"}:
        raise ValueError("Only harness.py and prompt.txt may evolve")
    tree = ast.parse(files["harness.py"])
    if not any(
        isinstance(n, ast.FunctionDef) and n.name == "run" and len(n.args.args) == 1
        for n in tree.body
    ):
        raise ValueError("Candidate must define run(api)")
    if not files["prompt.txt"].strip():
        raise ValueError("Prompt cannot be empty")


class MultimodalEvaluator:
    def __init__(self, config, space, run_dir):
        self.config, self.space, self.run_dir = config, space, run_dir
        role = config["roles"]["executor"]
        self.adapter = adapter_for(config, ChatModel(config["providers"][role["provider"]], role))
        self.fingerprint = self.adapter.fingerprint
        self.reuse = {}
        for run in config.get("reuse_from", []):
            previous = read_json(Path(run) / "frozen-selection.json")["experiment"]
            for key in ("adapter", "providers", "tasks"):
                if previous[key] != config[key]:
                    raise ValueError(f"Reuse {key} mismatch")
            if previous["roles"]["executor"] != config["roles"]["executor"]:
                raise ValueError("Reuse executor configuration mismatch")
            # Evolution code may differ; execution model, adapter and runtime source may not.
            for key, sha in previous["code_fingerprint"]["src"].items():
                if key.startswith(("mm_harness/runtimes/", "mm_harness/core/")):
                    if config["code_fingerprint"]["src"].get(key) != sha:
                        raise ValueError("Reuse executor shared source mismatch")
            for key, sha in previous["code_fingerprint"]["benchmarks"].items():
                if (
                    key.startswith(config["benchmark"] + "/")
                    and config["code_fingerprint"]["benchmarks"].get(key) != sha
                ):
                    raise ValueError("Reuse benchmark source mismatch")
            for path in Path(run).rglob("outcome.json"):
                o = Outcome.from_dict(read_json(path))
                if o.status in ("success", "task_failure"):
                    self.reuse[(o.task_id, o.harness_id, o.repetition, o.split)] = o

    async def evaluate(self, candidate, cases, context):
        observations = []
        # Upstream immutable component map is authoritative, expanded into real Python/prompt files.
        files = self.space._load(candidate.candidate_id)
        for case in cases:
            if case.split != context.split:
                raise ValueError("Evaluation case split mismatch")
            for repetition in range(context.repetitions):
                cached = context.attempt_sink.completed(
                    candidate_id=candidate.candidate_id, case_id=case.case_id, repetition=repetition
                )
                if cached is not None:
                    observations.append(cached)
                    continue
                attempt_id, number = context.attempt_sink.start(
                    candidate_id=candidate.candidate_id, case_id=case.case_id, repetition=repetition
                )
                root = (
                    context.artifact_dir
                    / digest([case.case_id, repetition])[:16]
                    / f"attempt-{number}"
                )
                root.mkdir(parents=True, exist_ok=True)
                source = root / "harness"
                source.mkdir(exist_ok=True)
                for name, content in files.items():
                    (source / name).write_text(content)
                task = Task(
                    case.case_id,
                    self.config["benchmark"],
                    SPLITS[case.split],
                    case.payload["group"],
                    dict(case.payload["input"]),
                )
                reused = self.reuse.get(
                    (task.task_id, candidate.candidate_id, repetition, task.split)
                )
                if reused is not None:
                    outcome = reused
                    write_json(
                        root / "reuse.json", {"source": outcome.rollout, "new_sampling": False}
                    )
                elif (root / "outcome.json").exists():
                    outcome = Outcome.from_dict(read_json(root / "outcome.json"))
                else:
                    outcome = await asyncio.to_thread(
                        self.adapter.run, task, source, candidate.candidate_id, repetition, root
                    )
                    write_json(root / "outcome.json", outcome.to_dict())
                if (
                    outcome.task_id,
                    outcome.harness_id,
                    outcome.repetition,
                    outcome.evaluator_id,
                ) != (case.case_id, candidate.candidate_id, repetition, self.fingerprint):
                    raise ValueError("Worker returned incorrect task/harness/repetition/evaluator")
                cost = Cost(
                    rollouts=0 if reused else 1,
                    input_tokens=0 if reused else outcome.cost.input_tokens,
                    output_tokens=0 if reused else outcome.cost.output_tokens,
                    wall_seconds=0 if reused else outcome.cost.wall_seconds,
                )
                disposition = (
                    outcome.status
                    if outcome.status in ("success", "task_failure")
                    else "execution_error"
                )
                if disposition in ("success", "task_failure"):
                    disposition = (
                        "success"
                        if outcome.score >= self.config.get("optimization_target", 1.0)
                        else "task_failure"
                    )
                observation = Observation.create(
                    candidate_id=candidate.candidate_id,
                    case_id=case.case_id,
                    split=case.split,
                    repetition=repetition,
                    disposition=disposition,
                    score=outcome.score,
                    evaluator_fingerprint=self.fingerprint,
                    attempts=number,
                    cost=cost,
                    metadata={
                        "outcome": outcome.to_dict(),
                        "attempt_id": attempt_id,
                        "reused": reused is not None,
                    },
                )
                context.attempt_sink.complete(attempt_id, observation, cost)
                observations.append(observation)
                print(
                    f"{case.split} {case.case_id} {candidate.candidate_id[:20]}: "
                    f"{outcome.status} score={outcome.score} {outcome.error or ''}",
                    flush=True,
                )
        return Evaluation(
            evaluation_id="sha256:" + digest(context.operation_id),
            candidate_id=candidate.candidate_id,
            split=context.split,
            purpose=context.purpose,
            iteration=context.iteration,
            requested_case_ids=tuple(c.case_id for c in cases),
            observations=tuple(observations),
            artifact_dir=ArtifactRef(
                uri=str(context.artifact_dir.relative_to(self.run_dir)), kind="multimodal-rollouts"
            ),
        )


class MultimodalEvidenceBuilder:
    def __init__(self, store, mode, max_images):
        self.store, self.mode, self.max_images = store, mode, max_images

    def build(self, evaluation):
        if evaluation.split != "train":
            raise ValueError("Validation/test evidence is not available to B")
        outcomes = [
            Outcome.from_dict(to_json_value(o.metadata["outcome"])) for o in evaluation.observations
        ]
        path = self.store.run_dir / "evidence" / digest(evaluation.evaluation_id) / "evidence.json"
        evidence = build_evidence(outcomes, self.mode, path, max_images=self.max_images)
        return self.store.write_json(
            str(path.relative_to(self.store.run_dir)),
            evidence,
            kind="multimodal-exploration-evidence",
        )


def validated_parent(candidate_ids, evaluations, policy):
    """Resume each round from the held-out incumbent, including after a rejected child."""
    latest = {}
    for value in sorted(evaluations, key=lambda e: e.get("iteration") or -1):
        if value["split"] == "development":
            latest[value["candidate_id"]] = [
                Outcome.from_dict(o["metadata"]["outcome"]) for o in value["observations"]
            ]
    selected = candidate_ids[0]
    for candidate in candidate_ids[1:]:
        if (
            selected in latest
            and candidate in latest
            and select(latest[selected], latest[candidate], **policy)["accepted"]
        ):
            selected = candidate
    return selected


class MultimodalPromptPack:
    def __init__(self, store, policy):
        self.store, self.policy = store, policy

    def session(self, kind, context):
        if kind == "diagnose_patch":
            evidence = read_json(self.store.run_dir / context["evidence"]["uri"])
            files = {"evidence.json": canonical(evidence)}
            schema = {
                "type": "object",
                "required": ["diagnosis", "updates", "expected_effect", "evidence_events"],
                "properties": {
                    "diagnosis": {"type": "string"},
                    "updates": {"type": "object"},
                    "expected_effect": {"type": "string"},
                    "evidence_events": {"type": "array"},
                },
                "additionalProperties": False,
            }
        else:
            if kind == "evolve":
                # Development artifacts live in upstream quarantine/dev. Replay the
                # authoritative events instead of guessing their storage projection.
                evaluations = [
                    to_json_value(event.payload["evaluation"])
                    for event in self.store.events_of_type("EvaluationCompleted")
                ]
                context = {
                    **context,
                    "selected_parent_id": validated_parent(
                        context["candidate_ids"], evaluations, self.policy
                    ),
                }
            files = {"control.json": canonical(dict(context))}
            schema = {"type": "object"}
        return SessionSpec(
            kind=kind,
            system_context="Frozen-model multimodal harness evolution",
            task_prompt=f"Run {kind} with the fixed phase-1 policy.",
            skills={},
            output_schema=schema,
            workspace_files=files,
            capabilities=frozenset(),
            mutation_label="multimodal-harness" if kind == "diagnose_patch" else None,
        )


class BoundedMultimodalProvider:
    """Actual pixel-carrying requests; control/reflection phases use fixed, logged policies."""

    def __init__(self, settings):
        self.settings = settings
        self.model = ChatModel(settings["provider"], settings["role"])

    async def run(self, request):
        import json

        kind = request.spec.kind
        if kind == "diagnose_patch":
            evidence = json.loads(request.spec.workspace_files["evidence.json"])
            files = read_json(request.workspace / "candidate.json")
            directory = request.trace_dir or request.workspace / "proposal"
            proposal = await asyncio.to_thread(
                propose, self.model, files, evidence, directory, seed=self.settings["seed"]
            )
            response = read_json(directory / "model" / "response.json")
            u = response["usage"]
            usage = Usage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
                model=self.model.role["model"],
                duration_seconds=response["seconds"],
                input_token_semantics="includes_cached_tokens",
            )
            if request.usage_observer:
                request.usage_observer(usage)
            return SessionResult(
                status="completed",
                structured_output=proposal,
                raw_response=response["text"],
                usage=(usage,),
                tool_calls=(),
                cost=Cost(
                    sessions=1,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    wall_seconds=response["seconds"],
                ),
            )
        context = json.loads(request.spec.workspace_files["control.json"])
        if kind == "evolve":
            output = {
                "schema_version": "autosaddler-evolution/v1",
                "parent_ids": [context["selected_parent_id"]],
                "component_sources": {},
                "rationale": "Fixed phase-1 policy: continue from the validation-selected incumbent",
            }
        elif kind == "reflect":
            output = {"schema_version": "autosaddler-reflection/v1", "lessons": []}
        else:
            raise ValueError(kind)
        return SessionResult(
            status="completed",
            structured_output=output,
            raw_response=canonical(output),
            tool_calls=(),
            usage=(),
            cost=Cost(),
        )


class ValidationEligible:
    """Exploration only checks validity; all valid children proceed to held-out validation."""

    def compare(self, parent, child):
        if parent.requested_case_ids != child.requested_case_ids:
            raise ValueError("Candidate exploration tasks changed")
        valid = all(o.is_valid for o in (*parent.observations, *child.observations))
        return PatchVerdict(
            before_score=parent.aggregate_score or 0,
            after_score=child.aggregate_score or 0,
            compared_case_ids=parent.requested_case_ids,
            accepted=valid,
            reason="eligible_for_validation" if valid else "incomplete_exploration",
        )


class CostRegressionRanking:
    def __init__(self, policy, run_dir):
        self.policy, self.run_dir = policy, run_dir

    def select(self, candidates):
        selected = candidates[0]
        records = []
        for pair in candidates[1:]:
            p = [
                Outcome.from_dict(to_json_value(o.metadata["outcome"]))
                for o in selected[1].observations
            ]
            c = [
                Outcome.from_dict(to_json_value(o.metadata["outcome"]))
                for o in pair[1].observations
            ]
            verdict = select(p, c, **self.policy)
            records.append(
                {"parent": selected[0].candidate_id, "candidate": pair[0].candidate_id, **verdict}
            )
            if verdict["accepted"]:
                selected = pair
        write_json(self.run_dir / "selection-comparison.json", records)
        return selected


def build_components(*, settings, base_dir, run_dir, store, ledger):
    del ledger
    config_path = (base_dir / settings["experiment"]).resolve()
    config = read_json(config_path)
    assert_same_model(config)
    tasks = [Task(**t) for t in config["tasks"]]
    validate_splits(tasks)
    source = Path(config["h0"])
    if config.get("h0_fingerprint") and tree_manifest(source) != config["h0_fingerprint"]:
        raise ValueError("Frozen H0 files changed")
    baseline = {name: (source / name).read_text() for name in ("harness.py", "prompt.txt")}
    space = ComponentMapHarnessSpace(
        baseline=baseline, store_root=run_dir / "candidates", validator=validate_components
    )
    cases = [
        Case(
            t.task_id,
            {"exploration": "train", "validation": "development"}[t.split],
            {"group": t.group, "input": t.payload},
        )
        for t in tasks
        if t.split != "test"
    ]
    return ScenarioComponents(
        name="mm_harness",
        version="1",
        harness_space=space,
        evaluator=MultimodalEvaluator(config, space, run_dir),
        evidence_builder=MultimodalEvidenceBuilder(
            store, config["evidence_mode"], config["max_images"]
        ),
        prompt_pack=MultimodalPromptPack(store, config["selection"]),
        train_cases=tuple(c for c in cases if c.split == "train"),
        development_cases=tuple(c for c in cases if c.split == "development"),
        required_capabilities=frozenset(),
        evaluation_repetitions=config["repetitions"],
        resolved_entities={
            "resolved/mm-experiment.json": config,
            "resolved/mm-code.json": config["code_fingerprint"],
            "resolved/mm-h0.json": baseline,
        },
    )


PLUGIN = ScenarioPlugin(
    name="mm_harness", api_version=SCENARIO_PLUGIN_API_VERSION, factory=build_components
)


def run(config_path: Path, run_id: str):
    import yaml
    from autosaddler.v2.config.registry import ScenarioRegistration, build_runtime, default_registry

    from mm_harness.core.store import RunStore

    upstream_config = yaml.safe_load(config_path.read_text())
    experiment = read_json(
        config_path.parent / upstream_config["scenario"]["settings"]["experiment"]
    )
    root = Path(__file__).resolve().parents[3]
    actual = {"src": tree_manifest(root / "src"), "benchmarks": tree_manifest(root / "benchmarks")}
    if actual != experiment["code_fingerprint"]:
        raise ValueError(
            "Execution source changed since configuration freeze; prepare a new experiment"
        )
    registry = default_registry()
    if "mm_harness" not in registry.scenarios:
        registry.register_scenario(ScenarioRegistration(plugin=PLUGIN, source="builtin"))
    registry.providers["mm_http"] = lambda *, ledger, settings: BoundedMultimodalProvider(settings)
    registry.acceptance["validation_eligible"] = ValidationEligible
    run_root = (config_path.parent / upstream_config["storage"]["run_root"]).resolve() / run_id
    registry.ranking["mm_cost_regression"] = lambda: CostRegressionRanking(
        experiment["selection"], run_root
    )
    guard = RunStore(run_root / "controller")
    try:
        runtime = build_runtime(config_path, run_id=run_id, registry=registry)
        result = runtime.engine.run()
        write_json(
            run_root / "frozen-selection.json",
            {
                **asdict(result),
                "experiment": experiment,
                "config_sha256": digest(experiment),
                "test_opened": False,
            },
        )
        return asdict(result)
    finally:
        guard.close()

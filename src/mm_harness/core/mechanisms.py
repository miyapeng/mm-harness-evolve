"""Research classification and versioned, evidence-bearing executable mechanism proposals.

Legacy records are views only: no inference of scope from old implementation tags.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field

MM_STAGES = ("acquire", "transform", "persist", "route", "ground", "verify")
MODALITIES = ("image", "video", "audio", "gui", "rendered_artifact", "document_visual", "mixed")
FAILURE_CLASSES = (
    "generic_harness",
    "multimodal_harness",
    "model_capability",
    "environment_evaluator",
    "insufficient_evidence",
)
PROPOSAL_SCHEMA = "mechanism-patch/v1"


@dataclass(frozen=True)
class RuntimeTrigger:
    """An observable event predicate, never a score threshold or executable expression."""

    event_kind: str
    description: str
    match: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.event_kind or not self.description or not isinstance(self.match, dict):
            raise ValueError(
                "Expected trigger requires an event kind, description and match object"
            )
        if self.event_kind in {"score", "evaluation", "gain", "success"}:
            raise ValueError("Expected trigger describes runtime behavior, not a score")


@dataclass(frozen=True)
class MechanismPatch:
    proposal_id: str
    scope: str
    primary_mm_stage: str | None
    secondary_mm_stages: list[str]
    modalities: list[str]
    failure_class: str
    failure_hypothesis: str
    evidence_refs: list[str]
    media_evidence_refs: list[str]
    mechanism_description: str
    why_generic_or_multimodal: str
    media_dependency: str | None
    expected_runtime_trigger: RuntimeTrigger
    expected_behavior_change: str
    implementation_targets: list[str]
    budget_effect: str
    invariants: list[str]
    risk_or_possible_regression: str
    source_diff: str | None = None
    frozen_candidate_identity: str | None = None
    schema: str = PROPOSAL_SCHEMA

    def __post_init__(self):
        if self.schema != PROPOSAL_SCHEMA or self.scope not in {"generic", "multimodal_specific"}:
            raise ValueError("Unknown mechanism schema/scope")
        if self.failure_class not in FAILURE_CLASSES:
            raise ValueError("Unknown failure classification")
        stages = (
            [self.primary_mm_stage] if self.primary_mm_stage else []
        ) + self.secondary_mm_stages
        if len(stages) != len(set(stages)) or any(s not in MM_STAGES for s in stages):
            raise ValueError("Unknown or duplicate MM stages")
        if any(m not in MODALITIES for m in self.modalities):
            raise ValueError("Unknown modality")
        if self.scope == "generic":
            if stages or self.media_dependency:
                raise ValueError("Generic mechanisms have no MM stages or media dependency")
            if self.failure_class != "generic_harness":
                raise ValueError("Generic mutation requires generic harness diagnosis")
        elif (
            not self.primary_mm_stage
            or not self.modalities
            or not self.media_dependency
            or not self.media_evidence_refs
            or self.failure_class != "multimodal_harness"
        ):
            raise ValueError(
                "MM mutation requires stage, modalities, media dependency/evidence and MM diagnosis"
            )
        for name in (
            "proposal_id",
            "failure_hypothesis",
            "mechanism_description",
            "why_generic_or_multimodal",
            "expected_behavior_change",
            "budget_effect",
            "risk_or_possible_regression",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"Missing {name}")
        for name in ("evidence_refs", "implementation_targets", "invariants"):
            if not getattr(self, name) or not all(
                isinstance(x, str) and x for x in getattr(self, name)
            ):
                raise ValueError(f"Missing {name}")
        if not isinstance(self.expected_runtime_trigger, RuntimeTrigger):
            raise ValueError("Expected runtime trigger must be structured")

    @property
    def mm_stages(self):
        return ([self.primary_mm_stage] if self.primary_mm_stage else []) + self.secondary_mm_stages

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        value = deepcopy(value)
        value["expected_runtime_trigger"] = RuntimeTrigger(**value["expected_runtime_trigger"])
        return cls(**value)


def load_proposal(value: dict) -> dict:
    """Read new specs or return a non-mutating legacy view, including old result wrappers."""
    raw = deepcopy(value)
    proposal = raw.get("proposal", raw)
    spec = proposal.get("mechanism_patch", proposal)
    if spec.get("schema") == PROPOSAL_SCHEMA:
        return {
            "taxonomy": PROPOSAL_SCHEMA,
            "mechanism_patch": MechanismPatch.from_dict(spec),
            "raw": raw,
        }
    if isinstance(spec.get("schema"), str) and spec["schema"].startswith("mechanism-patch/"):
        raise ValueError("Unsupported MechanismPatch schema")
    return {
        "taxonomy": "legacy_taxonomy",
        "scope": None,
        "primary_mm_stage": None,
        "secondary_mm_stages": None,
        "modalities": None,
        "mechanism_patch": None,
        "legacy_tags": proposal.get("mechanism_category"),
        "raw": raw,
    }

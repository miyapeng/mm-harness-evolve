"""Lightweight runtime event instrumentation; absence without coverage is unknown."""

from __future__ import annotations

from .mechanisms import MM_STAGES, RuntimeTrigger


class MechanismRecorder:
    def __init__(self, trace, *, role="A"):
        if role not in {"A", "B"}:
            raise ValueError("Unknown execution/evolution role")
        self.trace, self.role = trace, role

    def artifact(self, artifact, *, stage="acquire", mechanism_id=None):
        if stage not in {"acquire", "transform", "persist"}:
            raise ValueError("Artifact event stage invalid")
        return self.trace.add(
            "media_artifact",
            media=[
                {
                    "path": artifact.storage_ref,
                    "sha256": artifact.content_hash,
                    "mime_type": artifact.metadata.get("mime_type", "application/octet-stream"),
                }
            ]
            if artifact.storage_ref and artifact.content_hash
            else [],
            artifact=artifact.to_dict(),
            stage=stage,
            role=self.role,
            mechanism_id=mechanism_id,
        )

    def use(self, use, *, mechanism_id=None):
        if use.role != self.role:
            raise ValueError("MediaUse role mismatch")
        return self.trace.add(
            "media_use", use=use.to_dict(), role=self.role, mechanism_id=mechanism_id
        )

    def behavior(self, stage, *, artifact_ids, mechanism_id=None, **details):
        if stage not in MM_STAGES or not artifact_ids:
            raise ValueError("MM behavior requires a stage and explicit media identities")
        return self.trace.add(
            "mechanism_behavior",
            stage=stage,
            artifact_ids=artifact_ids,
            mechanism_id=mechanism_id,
            role=self.role,
            **details,
        )


def summarize_mechanisms(
    events, *, role="A", proposal=None, implemented=False, coverage_complete=False
):
    counts = dict.fromkeys(
        (
            "media_presentations",
            "unknown_freshness_routed",
            "media_acquisitions",
            "transformed_artifacts",
            "media_revisits",
            "stale_artifacts_routed",
            "fresh_artifacts_routed",
            "grounded_multimodal_actions",
            "multimodal_verification_events",
        ),
        0,
    )
    relevant = [e for e in events if e.get("payload", {}).get("role") == role]
    for event in relevant:
        p = event["payload"]
        if event["kind"] == "media_artifact":
            if p["stage"] == "acquire":
                counts["media_acquisitions"] += 1
            if p["stage"] == "transform":
                counts["transformed_artifacts"] += 1
        if event["kind"] == "media_use":
            u = p["use"]
            if u.get("passed_to_model") is True:
                counts["media_presentations"] += 1
                counts["unknown_freshness_routed"] += u["freshness_state"] == "unknown"
                counts["media_revisits"] += u.get("revisit") is True
                for freshness in ("fresh", "stale"):
                    counts[f"{freshness}_artifacts_routed"] += u["freshness_state"] == freshness
        if event["kind"] == "mechanism_behavior":
            counts["grounded_multimodal_actions"] += p["stage"] == "ground"
            counts["multimodal_verification_events"] += p["stage"] == "verify"
    state = "trigger_unknown"
    if proposal is not None:
        trigger = proposal.expected_runtime_trigger
        if not isinstance(trigger, RuntimeTrigger):
            raise ValueError("Unstructured trigger")
        matches = [
            e["event_id"]
            for e in relevant
            if e["kind"] == trigger.event_kind
            and e["payload"].get("mechanism_id") == proposal.proposal_id
            and all(e["payload"].get(k) == v for k, v in trigger.match.items())
        ]
        if matches:
            state = "triggered"
        elif coverage_complete:
            state = "not_triggered"
    else:
        matches = []
    return {
        "schema": "mechanism-observability/v1",
        "role": role,
        "counts": counts,
        "counts_are_lower_bounds": not coverage_complete,
        "implemented": implemented,
        "implementation_status": "implemented" if implemented else "unknown",
        "trigger_status": state,
        "matching_event_ids": matches,
        "semantic_effect_verified": False,
    }

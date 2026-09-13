"""Validate evidence linkage and source boundaries, not the truth of B's reasoning."""

from mm_harness.core.artifacts import contained, read_json
from mm_harness.core.mechanisms import FAILURE_CLASSES, MechanismPatch

from .mutation_boundary import check_boundary


def review_mechanism(workspace, parent, proposal, diagnosis, policy, parent_id):
    errors, mechanism = [], None
    if not isinstance(diagnosis, dict):
        return {"valid": False, "errors": ["Missing diagnosis"], "mechanism": None}
    if (
        not diagnosis.get("diagnosis_id")
        or diagnosis.get("parent_harness_id") != parent_id
        or diagnosis.get("failure_class") not in FAILURE_CLASSES
        or proposal.get("diagnosis_id") != diagnosis.get("diagnosis_id")
    ):
        errors.append("Diagnosis identity or classification invalid")
    if not diagnosis.get("reason"):
        errors.append("Diagnosis must separate facts, hypothesis and uncertainty in reason")
    if proposal.get("status") == "no_change":
        if not diagnosis.get("reason"):
            errors.append("no_change requires a reason (including insufficient evidence)")
        return {"valid": not errors, "errors": errors, "mechanism": None}
    try:
        mechanism = MechanismPatch.from_dict(proposal["mechanism_patch"])
        catalog = read_json(workspace / "media-catalog.json")
        if mechanism.failure_class != diagnosis.get("failure_class"):
            errors.append("Diagnosis and mechanism failure classification differ")
        if not set(mechanism.evidence_refs).issubset(catalog["event_refs"]):
            errors.append("Unresolved trajectory evidence references")
        if not set(mechanism.media_evidence_refs).issubset(catalog["artifact_ids"]):
            errors.append("Unresolved media evidence references")
        for media_ref in mechanism.media_evidence_refs:
            if not set(catalog.get("artifact_event_refs", {}).get(media_ref, [])).intersection(
                mechanism.evidence_refs
            ):
                errors.append("Media evidence must be linked to a cited trajectory event")
        checks = diagnosis.get("source_checks", [])
        if not checks:
            errors.append(
                "Diagnosis must locate actual source and describe observed defect/absence"
            )
        for check in checks:
            path = contained(workspace / "source", check["path"])
            # Compare against parent to establish that B actually names existing baseline source.
            baseline = contained(parent / "source", check["path"])
            if not baseline.is_file() or not check.get("finding") or not check.get("symbol"):
                errors.append(f"Invalid source check: {path}")
        report = check_boundary(parent / "source", workspace / "source", policy, mechanism)
        errors.extend(report["errors"])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        errors.append(f"Invalid MechanismPatch: {exc}")
    return {
        "valid": not errors,
        "errors": errors,
        "mechanism": mechanism.to_dict() if mechanism else None,
        "diagnosis_truth_verified": False,
        "semantic_contracts_verified": False,
        "trigger_status": "trigger_unknown",
    }

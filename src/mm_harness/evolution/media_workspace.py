"""Canonical sidecar projection of exported evidence; never rewrites original rollouts."""

from dataclasses import replace

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.core.media_artifacts import MediaArtifact, MediaUse, project_legacy_media


def export_media_catalog(workspace, overview):
    all_ids, evidence_refs, artifact_events = [], [], {}
    for outcome in overview["outcomes"]:
        directory = workspace / outcome["directory"]
        refs = read_json(directory / "media-index.json")
        artifacts = project_legacy_media(
            refs,
            namespace=f"{outcome['task_id']}:{outcome['harness_id']}:{outcome['sample']}:{outcome['events_sha256']}",
        )
        events = read_json(directory / "events.json")
        uses = []
        extra_artifacts = []
        native_artifacts = [
            MediaArtifact(**e["payload"]["artifact"])
            for e in events
            if e.get("kind") == "media_artifact" and e.get("payload", {}).get("artifact")
        ]
        by_event = {e["event_id"]: e for e in events}
        for index, artifact in enumerate(artifacts):
            event = by_event[artifact.source_event_id]
            payload = event.get("payload", {})
            if event.get("kind") == "media_artifact" and "artifact" in payload:
                native = MediaArtifact(**payload["artifact"])
                artifact = replace(native, storage_ref=artifact.storage_ref)
                artifacts[index] = artifact
            # The same newly audited request is also present as an inline raw event.
            # Reuse its canonical identity; do not make a second unknown legacy use.
            if event.get("kind") == "model_request" and event.get("request_id"):
                matches = [
                    a
                    for a in native_artifacts
                    if a.provenance.get("request_id") == event["request_id"]
                    and a.content_hash == artifact.content_hash
                ]
                if matches:
                    artifacts[index] = replace(matches[0], storage_ref=artifact.storage_ref)
                    extra_artifacts.extend(
                        replace(a, storage_ref=artifact.storage_ref) for a in matches[1:]
                    )
                    event_ref = f"{outcome['directory']}#{event['event_id']}"
                    for match in matches:
                        artifact_events.setdefault(match.artifact_id, []).append(event_ref)
                    evidence_refs.append(event_ref)
                    continue
            # Legacy request files prove serialization; transport/freshness may be absent.
            if event.get("kind") == "model_request":
                transport = payload.get("media_transport_evidence")
                uses.append(
                    MediaUse(
                        use_id=f"{outcome['directory']}:{event['event_id']}:{index}",
                        artifact_id=artifact.artifact_id,
                        request_id=event["event_id"],
                        role="A",
                        representation="inline_image",
                        selection_reason="unknown_legacy_policy",
                        mm_stage="route",
                        freshness_state="unknown",
                        readable=True,
                        passed_to_model=True if transport else None,
                        from_transform=True if artifact.parent_artifact_ids else None,
                        source_event_id=event["event_id"],
                        transport_evidence=transport,
                    ).to_dict()
                )
            event_ref = f"{outcome['directory']}#{event['event_id']}"
            artifact_events.setdefault(artifact.artifact_id, []).append(event_ref)
            evidence_refs.append(event_ref)
        for event in events:
            if event.get("kind") == "media_use":
                uses.append(MediaUse(**event["payload"]["use"]).to_dict())
            evidence_refs.append(f"{outcome['directory']}#{event['event_id']}")
        # Multiple representations can point at the same occurrence; catalog identity is unique.
        artifacts = list({a.artifact_id: a for a in [*artifacts, *extra_artifacts]}.values())
        # Presence/readability is a separate inventory, never an invented model use.
        write_json(directory / "media-artifacts.json", [a.to_dict() for a in artifacts])
        write_json(directory / "media-uses.json", uses)
        write_json(
            directory / "media-availability.json",
            [
                {
                    "artifact_id": a.artifact_id,
                    "collected": True,
                    "readable_to_B": a.verify_content(workspace),
                    "understood_correctly": None,
                }
                for a in artifacts
            ],
        )
        outcome["media_artifacts"] = str(
            (directory / "media-artifacts.json").relative_to(workspace)
        )
        outcome["media_uses"] = str((directory / "media-uses.json").relative_to(workspace))
        all_ids.extend(a.artifact_id for a in artifacts)
    return {
        "schema": "media-catalog/v1",
        "artifact_ids": sorted(set(all_ids)),
        "event_refs": sorted(set(evidence_refs)),
        "artifact_event_refs": artifact_events,
        "note": "Unavailable freshness/transport/parent identity stays unknown; old runs are not migrated in place.",
    }

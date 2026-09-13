"""Audit actual outgoing media representations at the fixed transport boundary.

This records transmitted bytes, not inferred understanding or freshness. URL-only
requests cannot establish downloaded content identity. Token-count requests are not
model-generation media use. Parent/revisit ambiguity stays unknown.
"""

import base64
import hashlib
import re

from mm_harness.core.artifacts import digest, write_json
from mm_harness.core.media_artifacts import MediaArtifact, MediaUse


def inline_media(value):
    # Only native media content blocks count. A data URI quoted in text is not an image input.
    if isinstance(value, dict):
        source = value.get("source", {})
        kind = value.get("type")
        if kind == "image" and source.get("type") == "base64":
            yield source["media_type"], base64.b64decode(source["data"], validate=True)
        elif kind == "input_audio" and "input_audio" in value:
            audio = value["input_audio"]
            yield "audio/" + audio["format"], base64.b64decode(audio["data"], validate=True)
        elif kind in {"image_url", "video_url", "input_image"}:
            field = value.get(kind, value.get("image_url", {}))
            url = field.get("url", "") if isinstance(field, dict) else field
            match = re.fullmatch(
                r"data:((?:image|audio|video)/[^;,\s]+);base64,([A-Za-z0-9+/=]+)", url
            )
            if match:
                yield match[1], base64.b64decode(match[2], validate=True)
        elif kind not in {"text", "input_text", "output_text"}:
            for v in value.values():
                yield from inline_media(v)
    elif isinstance(value, list):
        for v in value:
            yield from inline_media(v)


def audit_media_request(body, directory, *, role, transport_status, generation=True):
    artifacts, uses = [], []
    request_id = str(directory.resolve())
    for index, (mime, data) in enumerate(inline_media(body)):
        sha = hashlib.sha256(data).hexdigest()
        extension = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "audio/wav": ".wav",
            "audio/mp3": ".mp3",
            "video/mp4": ".mp4",
        }.get(mime, ".media")
        path = directory / "media" / (sha + extension)
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        artifact = MediaArtifact(
            artifact_id="request-media-" + digest([request_id, index, sha]),
            modality=mime.split("/")[0],
            content_hash=sha,
            storage_ref=str(path.relative_to(directory)),
            source_event_id=f"{directory.name}:request",
            metadata={"mime_type": mime},
            provenance={
                "origin": "actual_request_body",
                "request_id": request_id,
                "acquisition_event": "unknown",
                "original_artifact_identity": "unknown",
            },
        )
        artifacts.append(artifact.to_dict())
        # A successful generation response establishes receipt; network failure is ambiguous.
        # Failed HTTP generation may reject content before model consumption: stay unknown.
        passed = (
            True
            if generation and isinstance(transport_status, int) and 200 <= transport_status < 300
            else False
            if not generation
            else None
        )
        uses.append(
            MediaUse(
                use_id=f"{request_id}:{index}",
                artifact_id=artifact.artifact_id,
                request_id=request_id,
                role=role,
                representation="inline_bytes",
                selection_reason="runtime_policy_unspecified",
                mm_stage="route",
                freshness_state="unknown",
                readable=True,
                passed_to_model=passed,
                transport_evidence=f"HTTP:{transport_status}" if passed else None,
                source_event_id=artifact.source_event_id,
            ).to_dict()
        )
    write_json(
        directory / "media-audit.json",
        {
            "schema": "request-media-audit/v1",
            "artifacts": artifacts,
            "uses": uses,
            "generation": generation,
            "transport_status": transport_status,
            "coverage": "inline image/audio/video bytes only; external URL content unverified",
        },
    )

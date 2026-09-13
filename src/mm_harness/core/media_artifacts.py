"""Canonical media identities over existing content-addressed files, without binary JSON.

An artifact identifies an observation occurrence, not just a hash: two fresh captures
may have identical pixels. Freshness at request time lives in MediaUse, not a mutable
historical artifact record. Unknown provenance is retained as unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .artifacts import contained, digest, file_digest
from .mechanisms import MM_STAGES, MODALITIES

FRESHNESS = ("fresh", "stale", "unknown")


@dataclass(frozen=True)
class MediaArtifact:
    artifact_id: str
    modality: str
    content_hash: str | None
    storage_ref: str | None
    source_event_id: str | None = None
    source_tool_call_id: str | None = None
    created_step: int | None = None
    parent_artifact_ids: list[str] = field(default_factory=list)
    transform_chain: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    freshness_state: str = "unknown"
    provenance: dict = field(default_factory=dict)
    schema: str = "media-artifact/v1"

    def __post_init__(self):
        if self.schema != "media-artifact/v1":
            raise ValueError("Unknown artifact schema")
        if not self.artifact_id or self.modality not in MODALITIES:
            raise ValueError("Invalid artifact identity/modality")
        if self.content_hash is not None and (
            len(self.content_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.content_hash)
        ):
            raise ValueError("content_hash must be SHA256 of original stored bytes")
        if self.freshness_state not in FRESHNESS or self.artifact_id in self.parent_artifact_ids:
            raise ValueError("Invalid freshness or self-parent")
        if self.parent_artifact_ids and not self.transform_chain:
            raise ValueError("Derived media requires its transform chain")
        if self.transform_chain and not self.parent_artifact_ids:
            raise ValueError("Transformed media requires parent identity")

    def to_dict(self):
        return asdict(self)

    def verify_content(self, root: Path) -> bool:
        if self.storage_ref is None or self.content_hash is None:
            return False
        path = contained(root, self.storage_ref)
        return path.is_file() and file_digest(path) == self.content_hash

    @classmethod
    def from_file(cls, root, path, *, modality, source_event_id, **kwargs):
        path = contained(root, path)
        sha = file_digest(path)
        identity = digest([str(root.resolve()), str(path.relative_to(root)), source_event_id, sha])
        return cls(
            artifact_id=f"media-{identity}",
            modality=modality,
            content_hash=sha,
            storage_ref=str(path.relative_to(root)),
            source_event_id=source_event_id,
            **kwargs,
        )

    @classmethod
    def from_legacy(cls, ref, *, source_event_id=None, namespace="legacy"):
        sha = ref.get("sha256")
        mime = ref.get("mime_type", "image/unknown")
        modality = (
            "video"
            if mime.startswith("video/")
            else "audio"
            if mime.startswith("audio/")
            else "image"
        )
        return cls(
            artifact_id="media-"
            + digest([namespace, source_event_id, sha, ref.get("original_path")]),
            modality=modality,
            content_hash=sha,
            storage_ref=ref.get("path"),
            source_event_id=source_event_id,
            source_tool_call_id=ref.get("source_tool_call_id"),
            created_step=ref.get("created_step"),
            freshness_state=ref.get("freshness_state", "unknown"),
            metadata={
                k: ref[k]
                for k in ("width", "height", "mime_type", "timestamp_seconds", "crop_xyxy")
                if k in ref
            },
            provenance={
                "origin": "legacy_projection",
                "source_sha256": ref.get("source_sha256"),
                "ancestry_status": "unresolved" if ref.get("source_sha256") else "unknown",
            },
        )


def derive_artifact(root, path, *, parents, transform, source_event_id, modality="image", **kwargs):
    if not parents or not all(p.verify_content(root) for p in parents):
        raise ValueError("Derived artifact requires verified original parent files")
    return MediaArtifact.from_file(
        root,
        path,
        modality=modality,
        source_event_id=source_event_id,
        parent_artifact_ids=[p.artifact_id for p in parents],
        transform_chain=[*parents[0].transform_chain, transform],
        provenance={
            "origin": "runtime_transform",
            "parent_hashes": {p.artifact_id: p.content_hash for p in parents},
        },
        **kwargs,
    )


def validate_artifact_graph(artifacts):
    catalog = {a.artifact_id: a for a in artifacts}
    if len(catalog) != len(artifacts):
        raise ValueError("Duplicate artifact identity")

    def visit(identity, ancestors):
        if identity not in catalog or identity in ancestors:
            raise ValueError("Missing parent or cyclic provenance")
        for parent in catalog[identity].parent_artifact_ids:
            visit(parent, ancestors | {identity})

    for identity in catalog:
        visit(identity, set())
    return catalog


@dataclass(frozen=True)
class MediaUse:
    use_id: str
    artifact_id: str
    request_id: str | None
    role: str
    representation: str
    selection_reason: str
    mm_stage: str
    freshness_state: str
    readable: bool | None
    passed_to_model: bool | None
    from_transform: bool | None = None
    revisit: bool | None = None
    source_event_id: str | None = None
    transport_evidence: str | None = None
    understood_correctly: bool | None = None
    schema: str = "media-use/v1"

    def __post_init__(self):
        if self.mm_stage not in MM_STAGES or self.freshness_state not in FRESHNESS:
            raise ValueError("Invalid media use stage/freshness")
        if self.role not in {"A", "B"}:
            raise ValueError("Media use must distinguish execution A from evolution B")
        if self.passed_to_model is True and (not self.request_id or not self.transport_evidence):
            raise ValueError("Actual media passing needs request and transport evidence")
        if self.understood_correctly is not None:
            raise ValueError("Media transmission alone cannot establish understanding")

    def to_dict(self):
        return asdict(self)


def project_legacy_media(refs, *, namespace):
    """Read-only projection; a unique recorded source hash resolves a derived parent.

    Hash ambiguity (same pixels across captures) remains unresolved, never guessed.
    """
    artifacts = [
        MediaArtifact.from_legacy(r, source_event_id=r.get("event_id"), namespace=namespace)
        for r in refs
    ]
    result = []
    for artifact, ref in zip(artifacts, refs, strict=True):
        parent_hash = ref.get("source_sha256")
        parents = (
            [
                a
                for a in artifacts
                if a.content_hash == parent_hash and a.artifact_id != artifact.artifact_id
            ]
            if parent_hash
            else []
        )
        if len(parents) == 1:
            artifact = replace(
                artifact,
                parent_artifact_ids=[parents[0].artifact_id],
                transform_chain=[
                    {
                        "operation": "crop"
                        if "crop_xyxy" in ref
                        else "frame"
                        if "timestamp_seconds" in ref
                        else "unknown",
                        "crop_xyxy": ref.get("crop_xyxy"),
                        "timestamp_seconds": ref.get("timestamp_seconds"),
                    }
                ],
                provenance={**artifact.provenance, "ancestry_status": "hash_resolved"},
            )
        result.append(artifact)
    return result

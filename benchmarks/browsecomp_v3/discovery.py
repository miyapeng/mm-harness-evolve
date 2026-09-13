"""Read decrypted sample metadata without exposing answers, subgoals or full metadata.

The release filename train.jsonl does not establish a research development split.
Raw encrypted data must first be processed with the pinned upstream separately.
"""

import json
from pathlib import Path

from mm_harness.core.artifacts import contained, file_digest
from mm_harness.core.schema import Task


def _images(value):
    if value is None:
        return []
    if isinstance(value, str):
        if value.startswith("["):
            return _images(json.loads(value))
        return [value] if value else []
    if isinstance(value, list) and all(isinstance(s, str) for s in value):
        return value
    raise ValueError("Unsupported upstream image field")


def discover(samples: Path):
    tasks, seen = [], set()
    for path in sorted(samples.glob("*.json")):
        row = json.loads(path.read_text())
        if not isinstance(row.get("question"), str) or not row["question"]:
            raise ValueError(f"Missing public question: {path.name}")
        identity = str(row.get("id", path.stem))
        if identity in seen:
            raise ValueError("Duplicate task identity")
        seen.add(identity)
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        refs = (
            _images(row.get("image"))
            + _images(row.get("image_paths"))
            + _images(row.get("images"))
            + _images(metadata.get("images"))
        )
        images = []
        for ref in dict.fromkeys(refs):
            p = contained(samples, ref)
            if not p.is_relative_to((samples / "images").resolve()):
                raise ValueError("Only explicitly exported images/ assets may enter agent inputs")
            images.append({"path": str(p), "sha256": file_digest(p)})
        tasks.append(
            Task(
                identity,
                "browsecomp_v3",
                "unassigned",
                "unreviewed",
                {
                    "agent_input": {"question": row["question"], "images": images},
                    "upstream_split": "public_evaluation_release",
                    "development_approved": False,
                },
            )
        )
    return tasks

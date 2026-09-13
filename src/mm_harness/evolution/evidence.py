from __future__ import annotations

import json
import re
from pathlib import Path

from mm_harness.core.artifacts import digest, file_digest, write_json
from mm_harness.core.schema import Outcome


def text_without_pixels(value):
    """Native GUI traces can contain inline image blocks; text ablations must not carry them."""
    if isinstance(value, str):
        return re.sub(
            r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=]+",
            lambda match: f"[inline image sha256={digest(match.group())}]",
            value,
        )
    if isinstance(value, list):
        return [text_without_pixels(item) for item in value]
    if isinstance(value, dict):
        if (
            value.get("type") == "image"
            and isinstance(value.get("source"), dict)
            and value["source"].get("type") == "base64"
        ):
            return {"type": "image_reference", "sha256": digest(value["source"]["data"])}
        return {key: text_without_pixels(item) for key, item in value.items()}
    return value


def build_evidence(outcomes: list[Outcome], mode: str, out: Path, *, max_images=8) -> dict:
    if mode not in ("text", "multimodal"):
        raise ValueError("Evidence mode must be text or multimodal")
    if any(x.split != "exploration" for x in outcomes):
        raise ValueError("B evidence must come only from exploration tasks")
    records, images = [], []
    for outcome in outcomes:
        root = Path(outcome.rollout)
        events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()]
        if any(
            e["task_id"] != outcome.task_id or e["harness_id"] != outcome.harness_id for e in events
        ):
            raise ValueError("Trace/result task or harness mismatch")
        # Both conditions get identical event text and available-media metadata.
        records.append(
            {
                "task_id": outcome.task_id,
                "harness_id": outcome.harness_id,
                "status": outcome.status,
                "score": outcome.score,
                "metrics": outcome.metrics,
                "events": text_without_pixels(events),
            }
        )
        for e in events:
            for media in e["media"]:
                if not media["mime_type"].startswith("image/"):
                    continue
                path = root / media["path"]
                if file_digest(path) != media["sha256"]:
                    raise ValueError("Evidence image digest mismatch")
                images.append(
                    {
                        "path": str(path),
                        "task_id": outcome.task_id,
                        "event_id": e["event_id"],
                        "role": media["role"],
                        "sha256": media["sha256"],
                    }
                )
    # Round-robin by task prevents the first long trajectory consuming the entire image budget.
    groups = [[im for im in images if im["task_id"] == x.task_id] for x in outcomes]
    selected = []
    while any(groups) and len(selected) < max_images:
        for group in groups:
            if group and len(selected) < max_images:
                selected.append(group.pop(0))
    evidence = {
        "mode": mode,
        "records": records,
        "image_index": selected if mode == "multimodal" else [],
        "available_images": len(images),
        "image_budget": max_images,
    }
    write_json(out, evidence)
    return evidence

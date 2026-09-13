from __future__ import annotations

import math
import mimetypes
import shutil
from pathlib import Path

from .artifacts import file_digest


def copy_media(source: Path, root: Path, role: str, **metadata) -> dict:
    sha = file_digest(source)
    target = root / "media" / f"{sha}{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
    return {
        "path": str(target.relative_to(root)),
        "sha256": sha,
        "bytes": target.stat().st_size,
        "mime_type": mimetypes.guess_type(target)[0] or "application/octet-stream",
        "role": role,
        **metadata,
    }


def crop_media(root: Path, source: dict, box: tuple[int, int, int, int]) -> dict:
    from PIL import Image

    image = Image.open(root / source["path"])
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
        raise ValueError("Crop must be inside the original image")
    dest = root / "media" / f"crop-{source['sha256']}-{'-'.join(map(str, box))}.png"
    image.crop(box).save(dest)
    return {
        "path": str(dest.relative_to(root)),
        "sha256": file_digest(dest),
        "bytes": dest.stat().st_size,
        "mime_type": "image/png",
        "role": source["role"],
        "source_sha256": source["sha256"],
        "crop_xyxy": list(box),
    }


def video_frames(root: Path, source: dict, seconds: list[float], *, ffmpeg="ffmpeg") -> list[dict]:
    """Explicit timestamp expansion; retain raw video and its frame-to-source association."""
    from mm_harness.runtimes.process import run_process

    path = root / source["path"]
    if file_digest(path) != source["sha256"]:
        raise ValueError("Video changed before frame extraction")
    frames = []
    for timestamp in seconds:
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Frame timestamp must be finite and nonnegative")
        name = f"frame-{source['sha256']}-{timestamp:.6f}"
        dest = root / "media" / f"{name}.png"
        if not dest.exists():
            result = run_process(
                [
                    ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-n",
                    str(dest),
                ],
                cwd=root,
                directory=root / "frame-extraction" / name,
                timeout=60,
            )
            if result["returncode"] or not dest.exists():
                raise RuntimeError("Video frame extraction failed; inspect frame-extraction logs")
        frames.append(
            {
                "path": str(dest.relative_to(root)),
                "sha256": file_digest(dest),
                "bytes": dest.stat().st_size,
                "mime_type": "image/png",
                "role": source["role"],
                "source_sha256": source["sha256"],
                "timestamp_seconds": timestamp,
            }
        )
    return frames

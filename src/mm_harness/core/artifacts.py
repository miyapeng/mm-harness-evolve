from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w") as f:
        f.write(canonical(value) + "\n")
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


def tree_manifest(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): file_digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and not any(x in p.parts for x in ("__pycache__", ".git"))
    }


def contained(root: Path, relative: str) -> Path:
    p = root / relative
    if Path(relative).is_absolute() or not p.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path outside artifact root: {relative}")
    return p

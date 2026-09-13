from __future__ import annotations

import ast
import difflib
import json
import shutil
from pathlib import Path

from mm_harness.core.artifacts import contained, digest, read_json, tree_manifest, write_json


class CandidateStore:
    def __init__(self, root: Path, writable_paths: list[str]):
        self.root = root
        self.writable = set(writable_paths)
        root.mkdir(parents=True, exist_ok=True)

    def seed(self, source: Path) -> str:
        files = {k: (source / k).read_text() for k in tree_manifest(source)}
        return self._save(files)

    def _save(self, files: dict[str, str]) -> str:
        version = digest(files)
        root = self.root / version
        if root.exists():
            self.load(version)
            return version
        root.mkdir()
        for relative, content in files.items():
            path = contained(root / "source", relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        write_json(root / "manifest.json", {"id": version, "files": files})
        return version

    def load(self, version: str) -> dict[str, str]:
        root = contained(self.root, version)
        saved = read_json(root / "manifest.json")
        files = {k: (root / "source" / k).read_text() for k in tree_manifest(root / "source")}
        if saved != {"id": version, "files": files} or digest(files) != version:
            raise ValueError("Harness content does not match its version")
        return files

    def apply(self, parent: str, updates: dict[str, str], proposal_dir: Path) -> str:
        files = self.load(parent)
        write_json(proposal_dir / "requested-updates.json", updates)
        if not updates or not set(updates) <= self.writable:
            raise ValueError("Proposal must modify explicitly writable harness files")
        lines = []
        for name, content in sorted(updates.items()):
            contained(proposal_dir, name)
            if not isinstance(content, str):
                raise ValueError("Candidate file contents must be strings")
            lines.extend(
                difflib.unified_diff(
                    files.get(name, "").splitlines(True),
                    content.splitlines(True),
                    fromfile=f"a/{name}",
                    tofile=f"b/{name}",
                )
            )
            if name.endswith(".py"):
                ast.parse(content)
            if name.endswith(".json"):
                json.loads(content)
        (proposal_dir / "change.patch").write_text("".join(lines))
        files.update(updates)
        version = self._save(files)
        write_json(proposal_dir / "lineage.json", {"parent": parent, "candidate": version})
        return version

    def materialize(self, version: str, destination: Path) -> Path:
        self.load(version)
        shutil.copytree(self.root / version / "source", destination)
        return destination

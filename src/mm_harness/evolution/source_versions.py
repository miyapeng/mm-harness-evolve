"""Content-addressed copies of a real upstream harness, with reviewable patches."""

from __future__ import annotations

import ast
import difflib
import shutil
from pathlib import Path

import yaml

from mm_harness.core.artifacts import digest, read_json, tree_manifest, write_json


def snapshot(source: Path, destination: Path, *, parent: str | None = None) -> dict:
    # Never hard-link: a candidate must not mutate its parent through a shared inode.
    shutil.copytree(
        source,
        destination / "source",
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"
        ),
    )
    manifest = tree_manifest(destination / "source")
    record = {"id": digest(manifest), "parent": parent, "files": manifest}
    write_json(destination / "version.json", record)
    return record


def verify(directory: Path) -> dict:
    record = read_json(directory / "version.json")
    actual = tree_manifest(directory / "source")
    if actual != record["files"] or digest(actual) != record["id"]:
        raise ValueError(f"Harness source changed after freezing: {directory}")
    return record


def review(parent: Path, candidate_source: Path, *, allowed: list[str]) -> dict:
    """Check mutation scope and syntax; benchmark execution remains the actual check."""
    old = verify(parent)
    new = tree_manifest(candidate_source)
    changed = sorted(
        k for k in old["files"].keys() | new.keys() if old["files"].get(k) != new.get(k)
    )
    patches, errors = [], []
    for name in changed:
        if not any(
            name == rule or (rule.endswith("/") and name.startswith(rule)) for rule in allowed
        ):
            errors.append(f"outside mutation surface: {name}")
        before, after = parent / "source" / name, candidate_source / name
        if after.is_symlink() or (
            after.exists() and not after.resolve().is_relative_to(candidate_source.resolve())
        ):
            errors.append(f"candidate link outside source: {name}")
            continue
        try:
            old_text = before.read_text() if before.exists() else ""
            new_text = after.read_text() if after.exists() else ""
            diff_lines = difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{name}" if before.exists() else "/dev/null",
                tofile=f"b/{name}" if after.exists() else "/dev/null",
            )
            patches.extend(
                line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                for line in diff_lines
            )
            if after.exists() and (
                after.suffix == ".py"
                or (new_text.startswith("#!") and "python" in new_text.splitlines()[0])
            ):
                ast.parse(new_text, filename=name)
            elif after.suffix in (".yaml", ".yml") and after.exists():
                yaml.safe_load(new_text)
        except (UnicodeError, SyntaxError, yaml.YAMLError) as exc:
            errors.append(f"{name}: {exc}")
    return {
        "valid": not errors,
        "changed": changed,
        "errors": errors,
        "parent": old["id"],
        "id": digest(new),
        "patch": "".join(patches),
    }

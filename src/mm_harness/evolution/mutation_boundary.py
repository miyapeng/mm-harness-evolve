"""Stage/source boundary for new mechanism proposals; old policies remain versioned.

This establishes a syntactic boundary. Arbitrary code in shared runtime files still
requires behavior checks and fixed external permission/budget enforcement.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

import yaml

from mm_harness.core.artifacts import tree_manifest

FIXED_PATTERNS = (
    "**/scorer/**",
    "**/evaluator/**",
    "**/evaluation/**",
    "**/ground_truth/**",
    "**/hidden_answers/**",
    "**/oracle/**",
    "**/models.py",
    "**/provider*",
    "**/score_worker.py",
    "**/test_patch*",
    "**/solution*",
    "**/grader*",
)


def matches(path, pattern):
    return (
        path == pattern
        or (pattern.endswith("/") and path.startswith(pattern))
        or fnmatchcase(path, pattern)
        or fnmatchcase("/" + path, pattern)
    )


def boundary_files(policy):
    return sorted({item["path"] for item in policy["mutable"]})


def check_boundary(parent, candidate, policy, mechanism):
    from .mutation_policy import _at, _mask

    errors = []
    old, new = tree_manifest(parent), tree_manifest(candidate)
    changed = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
    if set(mechanism.implementation_targets) != set(changed):
        errors.append("implementation_targets must match all actual changed files")
    mapped_stages = set()
    for path in changed:
        fixed = [*FIXED_PATTERNS, *(p for group in policy["fixed"].values() for p in group)]
        if (
            PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or any(matches(path, p) for p in fixed)
        ):
            errors.append(f"Fixed boundary: {path}")
            continue
        entries = [
            e
            for e in policy["mutable"]
            if matches(path, e["path"])
            and mechanism.scope in e["scopes"]
            and (mechanism.scope == "generic" or set(mechanism.mm_stages) & set(e["mm_stages"]))
        ]
        if not entries:
            errors.append(f"Source not mapped to declared scope/stages: {path}")
            continue
        mapped_stages.update(s for e in entries for s in e["mm_stages"])
        if path.endswith((".yaml", ".yml")):
            # All unmapped fields (model, permissions, budgets, environment) stay identical.
            try:
                before, after = (
                    yaml.safe_load((parent / path).read_text()),
                    yaml.safe_load((candidate / path).read_text()),
                )
                for field in {p for e in entries for p in e.get("yaml_paths", [])}:
                    if field in policy.get("preserve_template_inputs", []):
                        import re

                        previous, current = str(_at(before, field)), str(_at(after, field))
                        if not set(re.findall(r"\{\{\s*(.*?)\s*\}\}", previous)).issubset(
                            set(re.findall(r"\{\{\s*(.*?)\s*\}\}", current))
                        ):
                            errors.append(f"Required template input removed: {field}")
                    _mask(before, field)
                    _mask(after, field)
                if before != after:
                    errors.append(f"Fixed YAML field changed: {path}")
            except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
                errors.append(f"Invalid mapped YAML: {exc}")
    if not set(mechanism.mm_stages).issubset(mapped_stages):
        errors.append("Declared MM stages lack changed implementation locations")
    return {
        "valid": not errors,
        "errors": errors,
        "changed_files": changed,
        "scope": mechanism.scope,
        "mm_stages": mechanism.mm_stages,
        "semantic_contracts_verified": False,
    }

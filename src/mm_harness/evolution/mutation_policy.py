"""Versioned mutation contracts: generic mechanisms plus benchmark code locations."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

from mm_harness.core.artifacts import read_json, tree_manifest


def resolve_policy(root: Path, config: dict) -> dict | None:
    if not config.get("mutation_policy"):
        return None
    policy = read_json(root / config["mutation_policy"])
    if policy.get("schema") == 2:
        taxonomy = read_json(root / policy["taxonomy"])
        if policy["categories"].keys() != taxonomy["categories"].keys():
            raise ValueError("Benchmark mapping must cover the shared mechanism categories")
        policy["shared_contract"] = taxonomy
    return policy


def allowed_files(policy: dict) -> list[str]:
    if policy.get("schema") == 3:
        from .mutation_boundary import boundary_files

        return boundary_files(policy)
    if policy.get("schema") != 2:
        return [policy["file"]]
    return sorted(
        ({policy["yaml_file"]} if policy.get("yaml_file") else set())
        | {path for item in policy["categories"].values() for path in item["files"]}
    )


def _matches(name, patterns):
    return any(name == p or (p.endswith("/") and name.startswith(p)) for p in patterns)


def check_mapped_policy(parent_source, candidate_source, policy, category, change_map):
    """Require a declared mechanism for every changed file, with benchmark-local mapping."""
    errors = []
    if (
        not isinstance(category, str)
        or category not in policy["categories"]
        or not isinstance(change_map, dict)
    ):
        return {"valid": False, "errors": ["Declare a primary category and per-file change_map"]}
    old, new = tree_manifest(parent_source), tree_manifest(candidate_source)
    changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    if set(change_map) != set(changed):
        errors.append("change_map must describe exactly the actual changed files")
    declared = []
    for name in changed:
        entry = change_map.get(name, {})
        if not isinstance(entry, dict):
            errors.append(f"Invalid change_map entry: {name}")
            continue
        kinds = entry.get("categories", [])
        if (
            not isinstance(kinds, list)
            or not kinds
            or any(not isinstance(k, str) or k not in policy["categories"] for k in kinds)
            or not entry.get("reason")
        ):
            errors.append(f"Missing category/reason for changed file: {name}")
            continue
        declared.extend(kinds)
        if name != policy.get("yaml_file"):
            if not any(_matches(name, policy["categories"][k]["files"]) for k in kinds):
                errors.append(f"File not mapped to the declared categories: {name}")
            continue
        try:
            before = yaml.safe_load((parent_source / name).read_text())
            after = yaml.safe_load((candidate_source / name).read_text())
            for path in {p for k in kinds for p in policy["categories"][k]["yaml_paths"]}:
                if path in policy.get("preserve_template_inputs", []):
                    old_value, new_value = _at(before, path), _at(after, path)
                    old_text = old_value if isinstance(old_value, str) else "\n".join(old_value)
                    new_text = new_value if isinstance(new_value, str) else "\n".join(new_value)
                    old_vars = set(re.findall(r"\{\{\s*(.*?)\s*\}\}", old_text))
                    new_vars = set(re.findall(r"\{\{\s*(.*?)\s*\}\}", new_text))
                    if not old_vars.issubset(new_vars):
                        errors.append(f"Preserve template inputs at {path}")
                _mask(before, path)
                _mask(after, path)
            if before != after:
                errors.append("Changed fixed or undeclared YAML fields")
        except (OSError, TypeError, KeyError, yaml.YAMLError) as exc:
            errors.append(f"Invalid mapped YAML: {exc}")
    if category not in declared:
        errors.append("The primary mechanism must appear in change_map")
    return {
        "valid": not errors,
        "errors": errors,
        "category": category,
        "changed_files": changed,
        "supporting_categories": sorted(set(declared) - {category}),
        "semantic_contracts_verified": False,
    }


def _at(tree, path):
    for key in path.split("."):
        tree = tree[key]
    return tree


def _mask(tree, path):
    parts = path.split(".")
    for key in parts[:-1]:
        tree = tree[key]
    tree[parts[-1]] = "<mutable>"


def check_policy(
    parent_source: Path,
    candidate_source: Path,
    policy: dict,
    category: str | None,
    change_map: dict | None = None,
) -> dict:
    """Check declared file/config scope, not the truth of a diagnosis or code semantics."""
    if policy.get("schema") == 2:
        return check_mapped_policy(parent_source, candidate_source, policy, category, change_map)
    errors = []
    if not isinstance(category, str) or category not in policy["categories"]:
        return {"valid": False, "errors": ["Choose one declared mechanism_category"]}
    try:
        before = yaml.safe_load((parent_source / policy["file"]).read_text())
        after = yaml.safe_load((candidate_source / policy["file"]).read_text())
        old_fixed, new_fixed = copy.deepcopy(before), copy.deepcopy(after)
        changed_paths = []
        for path in policy["categories"][category]["yaml_paths"]:
            old_value, new_value = _at(before, path), _at(after, path)
            if old_value != new_value:
                changed_paths.append(path)
            if path == "agent.history_processors":
                if not isinstance(new_value, list) or len(new_value) not in {1, 2}:
                    errors.append("Use only optional last_n_observations followed by image_parsing")
                elif new_value[-1] != {"type": "image_parsing"}:
                    errors.append("Keep the official image_parsing processor unchanged and last")
                elif len(new_value) == 2:
                    entry = new_value[0]
                    if (
                        not isinstance(entry, dict)
                        or entry.get("type") != "last_n_observations"
                        or set(entry) - {"type", "n", "polling"}
                        or type(entry.get("n")) is not int
                        or entry["n"] < 1
                        or type(entry.get("polling", 1)) is not int
                        or entry.get("polling", 1) < 1
                    ):
                        errors.append("Only positive integer n/polling for last_n_observations")
            else:
                if isinstance(old_value, str):
                    valid_text = isinstance(new_value, str) and bool(new_value.strip())
                else:
                    valid_text = (
                        isinstance(new_value, list)
                        and bool(new_value)
                        and all(isinstance(x, str) and x.strip() for x in new_value)
                    )
                if not valid_text:
                    errors.append(f"Expected nonempty reminder text at {path}")
                else:
                    old_text = old_value if isinstance(old_value, str) else "\n".join(old_value)
                    new_text = new_value if isinstance(new_value, str) else "\n".join(new_value)

                    def variables(text):
                        return set(re.findall(r"\{\{\s*(.*?)\s*\}\}", text))

                    if variables(old_text) != variables(new_text):
                        errors.append(f"Preserve template variables at {path}")
            _mask(old_fixed, path)
            _mask(new_fixed, path)
        if old_fixed != new_fixed:
            errors.append("Changed YAML outside the chosen mechanism category")
        if not changed_paths:
            errors.append("No mechanism value changed")
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        return {"valid": False, "errors": [f"Invalid policy configuration: {exc}"]}
    return {
        "valid": not errors,
        "errors": errors,
        "category": category,
        "changed_paths": changed_paths,
    }

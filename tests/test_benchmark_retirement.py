"""Retiring development entry points must not corrupt historical readers."""

import importlib
import json
from pathlib import Path

import pytest

from mm_harness.core.benchmarks import (
    adapter_for,
    benchmark_directory,
    check_configuration,
    mechanism_profile,
    research_pool,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["design2code", "claw_eval_mm"])
def test_archived_import_and_current_view_preserve_original_metadata(name):
    module = importlib.import_module(f"benchmarks.{name}.adapter")
    directory = benchmark_directory(name)
    assert Path(module.__file__).parent == directory
    metadata = directory / "mechanism-profile.json"
    before = metadata.read_bytes()
    original = json.loads(before)
    current = mechanism_profile(name)
    assert current.status == "archived"
    assert current.integration_status == original["integration_status"]
    assert (ROOT / current.mutation_boundary).is_file()
    assert original["status"] != "archived"
    assert metadata.read_bytes() == before
    assert not (ROOT / "configs/benchmarks" / f"{name}.json").exists()


@pytest.mark.parametrize("name", ["design2code", "claw_eval_mm"])
def test_archived_execution_requires_explicit_compatibility_opt_in(name):
    config = {"benchmark": name, "adapter": {"transport": "command"}}
    assert check_configuration(config)["configured"] is False
    with pytest.raises(ValueError, match="allow_archived"):
        adapter_for(config, None)
    # Construct only; no model, command or benchmark execution.
    assert adapter_for(config, None, allow_archived=True).benchmark == name


def test_removed_placeholders_are_not_discoverable_and_claw_assets_stay_put():
    for name in ["chartmimic", "visualwebarena"]:
        with pytest.raises(ValueError, match="removed"):
            benchmark_directory(name)
        assert not (ROOT / "benchmarks" / name).exists()
        assert not (ROOT / "configs/benchmarks" / f"{name}.json").exists()
    assert (ROOT / "benchmarks/claw_eval_mm/task-catalog.json").is_file()
    assert not (ROOT / "benchmarks/claw_eval_mm/__init__.py").exists()
    assert len(research_pool()) == 6
    assert {p.benchmark_id for p in research_pool(status="archived")} == {
        "design2code",
        "claw_eval_mm",
    }
    assert len(research_pool(status="all")) == 8

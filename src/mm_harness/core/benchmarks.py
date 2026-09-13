"""Benchmark discovery without importing heavyweight benchmark dependencies."""

import importlib
from pathlib import Path

from mm_harness.core.artifacts import read_json

NAMES = (
    "swe_mm",
    "gamedevbench",
    "vision2web",
    "osworld_verified",
    "agentic_vbench",
    "browsecomp_v3",
)
ARCHIVED_NAMES = ("design2code", "claw_eval_mm")


def benchmark_directory(name: str, root: Path | None = None) -> Path:
    """Resolve live or explicitly archived code/metadata without changing historical records."""
    root = root or Path(__file__).resolve().parents[3]
    if name in NAMES:
        return root / "benchmarks" / name
    if name in ARCHIVED_NAMES:
        return root / "archive/benchmarks" / name
    raise ValueError(f"Unknown or removed benchmark: {name}")


def profile(name: str, root: Path | None = None) -> dict:
    return read_json(benchmark_directory(name, root) / "profile.json")


def adapter_for(config, model, *, allow_archived=False):
    name = config["benchmark"]
    if name in ARCHIVED_NAMES and not allow_archived:
        raise ValueError(f"Archived benchmark {name}; explicit allow_archived=True required")
    benchmark_directory(name)
    adapter = config["adapter"]
    if name == "design2code" and adapter.get("transport") != "command":
        from benchmarks.design2code.adapter import Design2CodeAdapter

        return Design2CodeAdapter(adapter, model)
    if name == "vision2web" and adapter.get("transport") == "local_diagnostic":
        from benchmarks.vision2web.adapter import Vision2WebAdapter

        return Vision2WebAdapter(adapter, model)
    if name in ("vision2web", "design2code"):
        from mm_harness.runtimes.benchmark_command import CommandBenchmarkAdapter

        instance = CommandBenchmarkAdapter(adapter, model)
        instance.benchmark = name
        return instance
    return importlib.import_module(f"benchmarks.{name}.adapter").Adapter(adapter, model)


def check_configuration(config):
    """Static report only: it never probes a model or starts a benchmark service."""
    name = config["benchmark"]
    benchmark_directory(name)
    if name in ARCHIVED_NAMES:
        return {
            "benchmark": name,
            "configured": False,
            "missing": [],
            "environment_tested": False,
            "status": "archived",
            "reason": "Removed from current development; retained for historical compatibility",
        }
    adapter = config["adapter"]
    missing = []
    if adapter.get("transport") == "command" or name not in ("design2code", "vision2web"):
        missing = [
            f"commands.{key}"
            for key in ("execute", "score")
            if not adapter.get("commands", {}).get(key)
        ]
    return {
        "benchmark": name,
        "configured": not missing,
        "missing": missing,
        "environment_tested": False,
        "status": adapter.get("status", "configuration_only"),
    }


def mechanism_profile(name: str, root: Path | None = None):
    from dataclasses import replace

    from .benchmark_profiles import BenchmarkMechanismProfile

    value = BenchmarkMechanismProfile(
        **read_json(benchmark_directory(name, root) / "mechanism-profile.json")
    )
    if name in ARCHIVED_NAMES:
        # This is a current view; retain the archived JSON's original portfolio classification.
        value = replace(
            value,
            status="archived",
            mutation_boundary=f"archive/benchmarks/{name}/mutation-boundary.json",
        )
    return value


def research_pool(*, status="active", root: Path | None = None):
    return [
        p
        for name in (*NAMES, *ARCHIVED_NAMES)
        if (p := mechanism_profile(name, root)) and (status == "all" or p.status == status)
    ]

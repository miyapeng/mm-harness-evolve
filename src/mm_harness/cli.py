from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Multimodal harness evolution research runner")
    sub = parser.add_subparsers(dest="command", required=True)
    evolve = sub.add_parser("evolve")
    evolve.add_argument("--config", type=Path, required=True)
    evolve.add_argument("--run-id", required=True)
    benchmarks = sub.add_parser("benchmarks", help="List integration status; no environment calls")
    benchmarks.add_argument("--name")
    benchmarks.add_argument(
        "--all", action="store_true", help="Include archived compatibility entries"
    )
    benchmarks.add_argument(
        "--status",
        choices=["active", "archived", "reserve", "reserve_transfer", "legacy_smoke"],
        default="active",
    )
    check = sub.add_parser("check-config", help="Check wiring without starting benchmark services")
    check.add_argument("--config", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "benchmarks":
        from mm_harness.core.benchmarks import mechanism_profile, research_pool

        value = (
            mechanism_profile(arguments.name).to_dict()
            if arguments.name
            else [
                {
                    "benchmark": p.benchmark_id,
                    "status": p.status,
                    "integration_status": p.integration_status,
                    "mechanism_headroom": p.mechanism_headroom,
                }
                for p in research_pool(status="all" if arguments.all else arguments.status)
            ]
        )
        print(json.dumps(value, indent=2))
        return
    if arguments.command == "check-config":
        from mm_harness.core.benchmarks import check_configuration

        print(json.dumps(check_configuration(json.loads(arguments.config.read_text())), indent=2))
        return
    if arguments.command == "evolve":
        config = json.loads(arguments.config.read_text())
        experiment = json.loads(
            (arguments.config.parent / config["scenario"]["settings"]["experiment"]).read_text()
        )
        current = Path(__file__).resolve().parents[2]
        frozen = Path(experiment.get("code_root", current)).resolve()
        if frozen != current:
            project = arguments.config.resolve().parent.parent
            env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [
                        str(frozen / "src"),
                        str(frozen),
                        str(project / "third_party/AutoSaddler-main/src"),
                    ]
                ),
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mm_harness.cli",
                    "evolve",
                    "--config",
                    str(arguments.config.resolve()),
                    "--run-id",
                    arguments.run_id,
                ],
                cwd=frozen,
                env=env,
            )
            raise SystemExit(result.returncode)
        from mm_harness.evolution.autosaddler import run

        print(json.dumps(run(arguments.config.resolve(), arguments.run_id), indent=2))


if __name__ == "__main__":
    main()

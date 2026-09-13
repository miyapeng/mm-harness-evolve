"""Read-only local checks for the active SWE/Vision2Web native H0s; no model calls or jobs."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def probe(argv, root):
    try:
        result = subprocess.run(
            argv,
            cwd=root,
            env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "True"},
            text=True,
            capture_output=True,
            timeout=30,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "output": result.stdout[-1500:] if result.returncode == 0 else result.stderr[-1500:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}


def inspect(root):
    lock = json.loads((root / "third_party/lock.json").read_text())
    docker = (
        probe(["docker", "info", "--format", "{{.ServerVersion}}"], root)
        if shutil.which("docker")
        else {"ok": False, "error": "docker executable absent"}
    )
    benchmarks = {}
    settings = [
        ("vision2web", "Vision2Web", ".venv-vision2web/bin/vision2web"),
        ("swe_mm", "SWE-agent", ".venv-swe-agent/bin/sweagent"),
    ]
    for name, upstream, executable in settings:
        source = root / lock["upstreams"][upstream]["path"]
        manifest = json.loads((root / "benchmarks" / name / "upstream/SOURCE.json").read_text())
        mismatches = []
        for relative, expected in manifest["files"].items():
            path = source / relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                mismatches.append(relative)
        cli = probe([str(root / executable), "--help"], root)
        benchmarks[name] = {
            "source": str(source.relative_to(root)),
            "commit": lock["upstreams"][upstream]["commit"],
            "h0_source_matches_manifest": not mismatches,
            "mismatches": mismatches,
            "cli": cli,
            "native_rollout_verified": False,
            "evolution_worker_wired": False,
        }
    for name in ("vision2web", "swe_mm"):
        path = root / "experiments/provenance" / f"{name}-data-import.json"
        benchmarks[name]["data_import"] = json.loads(path.read_text()) if path.exists() else None
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local source hashes and native CLI startup; no inference, image pull or scoring",
        "docker": docker,
        "benchmarks": benchmarks,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect(root)
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(content)


if __name__ == "__main__":
    main()

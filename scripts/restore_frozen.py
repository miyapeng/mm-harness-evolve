"""Restore a recorded experiment source snapshot from its recorded Git commit."""

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    project = Path(__file__).resolve().parents[1]
    root = Path(config["code_root"])
    if not root.exists():
        archive = subprocess.check_output(
            ["git", "archive", config["git_commit"], "src", "benchmarks"], cwd=project
        )
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(root, filter="data")
    for area, files in config["code_fingerprint"].items():
        for relative, expected in files.items():
            path = root / area / relative
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(
                    f"Recorded source differs from Git commit: {path}; restore the original run snapshot"
                )
    if config.get("h0_files"):
        h0 = Path(config["h0"])
        h0.mkdir(parents=True, exist_ok=True)
        for name, data in config["h0_files"].items():
            path = h0 / name
            if path.exists() and path.read_text() != data:
                raise ValueError(f"Recorded H0 differs: {path}")
            if not path.exists():
                path.write_text(data)
    print(root, "verified")


if __name__ == "__main__":
    main()

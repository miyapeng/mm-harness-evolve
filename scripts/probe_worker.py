"""Run in the existing pinned Vision2Web image; write only to this project's runs."""

import concurrent.futures
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/data/miyapeng/mmcode/mm-harness-evolve")
OUT = ROOT / "runs" / "environment-probe"
OUT.mkdir(parents=True, exist_ok=True)


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=40)
        return {"returncode": p.returncode, "stdout": p.stdout[-6000:], "stderr": p.stderr[-2000:]}
    except Exception as e:
        return {"error": str(e)}


result = {"python": sys.version, "tools": {}, "packages": {}}
for name in ["claude", "openhands", "playwright-cli", "git", "node"]:
    result["tools"][name] = command([name, "--version"]) if shutil.which(name) else None
for name in ["claude-agent-sdk", "openhands-sdk", "playwright", "litellm", "jsonschema"]:
    try:
        result["packages"][name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pass
(OUT / "runtime.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)


def acquire(repo, name):
    path = ROOT / "third_party" / name
    if (path / ".git").exists():
        return {name: command(["git", "-C", str(path), "rev-parse", "HEAD"])}
    return {
        name: command(["git", "clone", "--depth", "1", f"https://github.com/{repo}.git", str(path)])
    }


with concurrent.futures.ThreadPoolExecutor(2) as pool:
    records = list(
        pool.map(
            lambda x: acquire(*x),
            [
                ("microsoft/AutoSaddler", "AutoSaddler-worker"),
                ("stanford-iris-lab/meta-harness", "meta-harness"),
            ],
        )
    )
(OUT / "upstream-acquisition.json").write_text(json.dumps(records, indent=2))
print(json.dumps(records), flush=True)

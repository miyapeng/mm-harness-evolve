"""Use the unmodified official inference engine and OpenHandsAdapter for one project."""

import argparse
import json
import os
import subprocess
from pathlib import Path


def command(root, *, task_type, project, model, base_url, output, api_key="<from environment>"):
    lock = json.loads((root / "third_party/lock.json").read_text())
    source = root / lock["upstreams"]["Vision2Web"]["path"]
    image = json.loads((root / "data/vision2web/image.json").read_text())
    return source, [
        str(root / ".venv-vision2web/bin/vision2web"),
        "inference",
        "--framework",
        "openhands",
        "--model",
        model,
        "--api-key",
        api_key,
        "--base-url",
        base_url,
        "--sandbox",
        f"{image['immutable_image']}@{image['target_digest']}",
        "--datasets-dir",
        str(root / "data/vision2web/extracted"),
        "--results-dir",
        str(output.resolve()),
        "--task",
        task_type,
        "--projects",
        project,
        "--max-workers",
        "1",
    ]


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-type", choices=["webpage", "frontend", "website"], required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-env", default="MM_HARNESS_API_KEY")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    kwargs = dict(
        task_type=args.task_type,
        project=args.project,
        model=args.model,
        base_url=args.base_url,
        output=args.output,
    )
    source, argv = command(root, **kwargs)
    print(json.dumps({"command": argv, "cwd": str(source), "executed": args.execute}, indent=2))
    if args.execute:
        if args.output.exists():
            raise FileExistsError("Use a fresh output directory for a new rollout")
        _, argv = command(root, **kwargs, api_key=os.environ[args.api_key_env])
        subprocess.run(argv, cwd=source, check=True)


if __name__ == "__main__":
    main()

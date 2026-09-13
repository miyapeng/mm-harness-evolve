"""Launch the pinned official SWE-agent multimodal configuration for one instance."""

import argparse
import json
import re
import subprocess
from pathlib import Path


def command(root, *, instance_id, model_config, output):
    lock = json.loads((root / "third_party/lock.json").read_text())
    source = root / lock["upstreams"]["SWE-agent"]["path"]
    return source, [
        str(root / ".venv-swe-agent/bin/sweagent"),
        "run-batch",
        "--config",
        str(source / "config/default_mm_with_images.yaml"),
        "--config",
        str(model_config.resolve()),
        "--instances.type",
        "file",
        "--instances.path",
        str(root / "data/swe_mm/dev/agent_visible/sweagent-instances.jsonl"),
        "--instances.filter",
        f"^{re.escape(instance_id)}$",
        "--output_dir",
        str(output.resolve()),
        "--num_workers",
        "1",
    ]


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    source, argv = command(
        root, instance_id=args.instance_id, model_config=args.model_config, output=args.output
    )
    print(json.dumps({"command": argv, "cwd": str(source), "executed": args.execute}, indent=2))
    if args.execute:
        if args.output.exists():
            raise FileExistsError("Use a fresh output directory for a new rollout")
        subprocess.run(argv, cwd=source, check=True)


if __name__ == "__main__":
    main()

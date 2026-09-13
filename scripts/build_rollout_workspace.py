"""Build an inspectable B evidence workspace without calling a model.

PYTHONPATH=src .venv/bin/python scripts/build_rollout_workspace.py --outcomes FILE \
    --parent-id HARNESS_ID --output runs/EXPERIMENT/evidence-preview
"""

import argparse
from pathlib import Path

from mm_harness.core.artifacts import read_json
from mm_harness.evolution.rollout_workspace import build_rollout_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--parent-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["text", "multimodal"], default="multimodal")
    args = parser.parse_args()
    result = build_rollout_workspace(
        read_json(args.outcomes),
        parent_id=args.parent_id,
        workspace=args.output,
        mode=args.mode,
        allowed_edits=[],
    )
    print(f"{args.output}/WORKSPACE.md: {len(result['outcomes'])} rollouts; no model called")


if __name__ == "__main__":
    main()

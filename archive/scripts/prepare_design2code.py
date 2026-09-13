"""Freeze the local smoke experiment before any model call. Never overwrites a config."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from mm_harness.core.artifacts import file_digest, tree_manifest, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="design2code-mm-smoke")
    parser.add_argument("--mode", choices=["text", "multimodal"], default="multimodal")
    parser.add_argument("--reuse-from", action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "configs" / f"{args.name}.json"
    if output.exists():
        raise FileExistsError(f"Use a new name: {output}")
    frozen = root / "experiments" / "frozen" / args.name
    for name in ("src", "benchmarks"):
        shutil.copytree(
            root / name, frozen / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    legacy = root / "third_party" / "MultimodalCode"
    data = root.parent / "MultimodalCode" / "data" / "design2code"
    base_role = {
        "provider": "local_qwen",
        "model": "Qwen3.5-9B",
        "revision": "local-Qwen3.5-9B-config-"
        + file_digest(Path("/data/miyapeng/model/Qwen3.5-9B/config.json")),
        "temperature": 0.0,
        "max_tokens": 8192,
        "timeout_seconds": 240,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    provider = {
        "protocol": "openai_chat",
        "base_url": "http://10.119.255.142:18002/v1",
        "api_key_env": "MM_HARNESS_API_KEY",
        "no_proxy": True,
    }
    tasks = []
    # These are development-only distinct page identities, not a paper split.
    for split, pairs in [
        ("exploration", [("0", "ecommercenews"), ("1", "glycofragwork")]),
        ("validation", [("3", "offshore-electrics"), ("4", "producer-application")]),
        ("test", [("5", "pillars"), ("6", "item-6-unresolved")]),
    ]:
        for task_id, group in pairs:
            image = data / "images" / f"image_{task_id}.png"
            tasks.append(
                {
                    "task_id": task_id,
                    "benchmark": "design2code",
                    "split": split,
                    "group": group,
                    "payload": {"image": str(image), "image_sha256": file_digest(image)},
                }
            )
    config = {
        "benchmark": "design2code",
        "code_root": str(frozen),
        "reuse_from": [str((root / p).resolve()) for p in args.reuse_from],
        "optimization_target": 1.0,
        "same_model": True,
        "roles": {
            "executor": {**base_role, "runtime": "direct_python"},
            "evolver": {**base_role, "runtime": "bounded_multimodal_http"},
        },
        "providers": {"local_qwen": provider},
        "h0": str(frozen / "benchmarks/design2code/h0"),
        "evidence_mode": args.mode,
        "max_images": 8,
        "repetitions": 1,
        "tasks": tasks,
        "selection": {
            "min_gain": 0.0,
            "max_regressions": 0,
            "max_token_ratio": 2.5,
            "success_threshold": 0.8,
        },
        "protocol": {
            "generation": "official_direct_image_only",
            "reference_html_visible": False,
            "split_status": "development_smoke_only; page identity labels; exact website/template mapping unresolved",
            "dataset_sha256": file_digest(data / "data.jsonl"),
            "model_revision_limit": "local config identity, not a verified immutable server-weight digest",
        },
        "git_commit": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip(),
        "code_fingerprint": {
            "src": tree_manifest(root / "src"),
            "benchmarks": tree_manifest(root / "benchmarks"),
        },
        "upstream": json.loads((root / "third_party/lock.json").read_text()),
        "adapter": {
            "dataset_file": str(data / "data.jsonl"),
            "seed": 20260909,
            "timeout_seconds": 480,
            "max_model_calls": 2,
            "success_threshold": 0.8,
            "placeholder": str(legacy / "evaluate/design2code/Design2Code/prompting/rick.jpg"),
            "evaluator_root": str(legacy / "evaluate/design2code"),
            "eval_python": "/data/miyapeng/miniconda3/envs/mmcode/bin/python",
            "legacy_src": str(legacy / "src"),
            "cache_root": str(root / "runs/cache"),
            "browsers_path": str(root.parent / "MultimodalCode/.runtime/research/playwright"),
            "node": "/data/miyapeng/miniconda3/envs/mmcode/lib/python3.10/site-packages/playwright/driver/node",
            "driver": "/data/miyapeng/miniconda3/envs/mmcode/lib/python3.10/site-packages/playwright/driver/package",
            "renderer": str(legacy / "scripts/render_playwright.js"),
        },
    }
    write_json(output, config)
    upstream = {
        "schema_version": "autosaddler/v2",
        "scenario": {"type": "mm_harness", "settings": {"experiment": output.name}},
        "optimization": {
            "task_selection": {"type": "fixed", "batch_size": 2},
            "acceptance": {"type": "validation_eligible"},
            "development": {"type": "full_on_accept"},
            "ranking": {"type": "mm_cost_regression"},
            "budget": {"max_rollouts": 8, "max_iterations": 1},
            "diagnosis_patch_timeout_seconds": 240,
            "session_retries": 0,
        },
        "provider": {
            "type": "mm_http",
            "capabilities": ["read_workspace", "edit_workspace", "network"],
            "settings": {
                "provider": provider,
                "role": config["roles"]["evolver"],
                "seed": 20260909,
            },
        },
        "storage": {"type": "local", "run_root": "../runs"},
    }
    write_json(output.with_suffix(".autosaddler.json"), upstream)
    print(output.with_suffix(".autosaddler.json"))


if __name__ == "__main__":
    main()

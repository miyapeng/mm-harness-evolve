"""Load the selected official SWE-agent source, with fixed task/provider settings.

Execute only inside a fresh official instance container and the task filesystem
sandbox. --check validates the real upstream configuration without a rollout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def native_config(source: Path, instance: dict, role: dict, base_url: str, output: Path) -> dict:
    config = yaml.safe_load((source / "config/default_mm_with_images.yaml").read_text())
    # These are fixed provider/budget settings, not part of the mutation surface.
    model = {
        "name": "openai/" + role["model"],
        "api_base": base_url,
        "api_key": "EMPTY",
        "temperature": role["temperature"],
        "top_p": role["top_p"],
        "per_instance_cost_limit": 0,
        # Pinned upstream checks calls > limit AFTER a successful request.
        # N-1 therefore enters its normal autosubmission on the Nth request.
        "per_instance_call_limit": role["max_requests"] - 1,
        "max_input_tokens": 122880,
        "max_output_tokens": role["max_tokens"],
        "completion_kwargs": {
            "max_tokens": role["max_tokens"],
            "timeout": role["request_timeout_seconds"],
            "extra_body": {"chat_template_kwargs": {"enable_thinking": role["enable_thinking"]}},
        },
    }
    config["agent"]["model"] = model
    return {
        "agent": config["agent"],
        "env": {
            "deployment": {"type": "local"},
            "repo": {
                "type": "preexisting",
                "repo_name": "testbed",
                "base_commit": instance["base_commit"],
                "reset": False,
            },
        },
        "problem_statement": {
            "type": "swe_bench_multimodal",
            "id": instance["instance_id"],
            "text": instance["problem_statement"],
            "issue_images": instance["extra_fields"]["issue_images"],
        },
        "output_dir": str(output),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.request.read_text())
    source = Path(spec["source"]).resolve()
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    sys.path.insert(0, str(source))
    import sweagent
    from sweagent.run.run_single import RunSingle, RunSingleConfig

    if Path(sweagent.__file__).resolve().parent.parent != source:
        raise RuntimeError("Loaded a different SWE-agent harness than the selected candidate")
    config = RunSingleConfig.model_validate(
        native_config(
            source, spec["instance"], spec["role"], spec["base_url"], Path(spec["output"])
        )
    )
    if args.check:
        print(
            json.dumps(
                {
                    "status": "configuration_valid",
                    "source": str(source),
                    "task_id": config.problem_statement.id,
                    "model": config.agent.model.name,
                    "deployment": config.env.deployment.type,
                    "rollout_executed": False,
                }
            )
        )
        return
    if os.environ.get("MM_HARNESS_ISOLATED_TASK") != "1":
        raise RuntimeError("Run through the task sandbox inside a fresh official instance image")
    base = subprocess.check_output(
        ["git", "-C", "/testbed", "rev-parse", "HEAD"], text=True
    ).strip()
    clean = subprocess.run(["git", "-C", "/testbed", "diff", "--quiet", "HEAD"], check=False)
    if base != spec["instance"]["base_commit"] or clean.returncode:
        raise RuntimeError("Instance must start from the pristine fixed base commit")
    output = Path(spec["output"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "loaded-config.json").write_text(config.model_dump_json(indent=2))
    (output / "identity.json").write_text(json.dumps(spec["identity"], indent=2))
    RunSingle.from_config(config).run()


if __name__ == "__main__":
    main()

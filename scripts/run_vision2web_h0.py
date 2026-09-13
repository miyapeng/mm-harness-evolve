"""New local OpenHands rollout; explicitly generation-only until official scoring is run."""

import argparse
import json
from pathlib import Path

from benchmarks.vision2web.adapter import Vision2WebAdapter
from mm_harness.core.artifacts import digest, write_json
from mm_harness.core.schema import Task
from mm_harness.runtimes.model import ChatModel

parser = argparse.ArgumentParser()
parser.add_argument("--case", default="webpage/cloudera")
parser.add_argument("--run-id", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = root / "runs" / args.run_id
if output.exists():
    raise FileExistsError("Use a new run-id for a fresh generation sample")
provider = {"base_url": "http://10.119.255.142:18002/v1", "no_proxy": True}
role = {
    "model": "Qwen3.5-9B",
    "temperature": 0.0,
    "max_tokens": 8192,
    "timeout_seconds": 240,
    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
}
legacy = root / "third_party/MultimodalCode"
config = {
    "python": str(root / ".venv-openhands/bin/python"),
    "openhands_src": str(legacy / "scaffolds/openhands/src"),
    "extensions": str(legacy / "scaffolds/openhands/extensions"),
    "max_model_calls": 20,
    "timeout_seconds": 900,
    "scoring": "not_yet_run",
    "transport": "local-isolated-directory",
    "upstream": "Vision2Web 577f939; OpenHands CLI 1.16.0 SDK 1.21.0",
    "compatibility": [
        "workspace path translation",
        "frozen skills discovery",
        "model metadata gateway",
        "newly resolved transitive dependencies; not the pinned container environment",
    ],
}
task = Task(
    args.case,
    "vision2web",
    "exploration",
    args.case.split("/")[1],
    {"source_dir": str(root / "data/vision2web/extracted" / args.case)},
)
h0 = root / "benchmarks/vision2web/h0"
files = {p.name: p.read_text() for p in h0.iterdir() if p.is_file()}
version = "sha256:" + digest(files)
write_json(
    output / "resolved.json",
    {
        "config": config,
        "provider": provider,
        "role": role,
        "task": task.__dict__,
        "harness_id": version,
        "harness": files,
    },
)
result = Vision2WebAdapter(config, ChatModel(provider, role)).run(task, h0, version, 0, output)
write_json(output / "outcome.json", result.to_dict())
print(json.dumps(result.to_dict(), indent=2))

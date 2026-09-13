"""Load the actual candidate inside a benchmark environment and call its API hook.

The benchmark integrator supplies --factory module:create_api. It returns an object
with prompt and execute_upstream(recipe), using the official harness/runtime.
No default implementation pretends to run an unavailable upstream benchmark.
"""

import argparse
import importlib
import importlib.util
from pathlib import Path

from mm_harness.core.artifacts import digest, read_json, write_json


def execute(request, factory):
    files = request["harness"]["files"]
    if "sha256:" + digest(files) != request["harness_id"]:
        raise ValueError("Worker candidate identity mismatch")
    root = Path(request["workspace"]) / "_harness"
    root.mkdir(parents=True, exist_ok=True)
    for name in ("harness.py", "prompt.txt"):
        (root / name).write_text(files[name])
    spec = importlib.util.spec_from_file_location("attempt_harness", root / "harness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    api = factory(request)
    api.prompt = files["prompt.txt"]
    result = module.run(api)
    return {**result, **{key: request[key] for key in ("task_id", "harness_id", "repetition")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--factory", required=True, help="Benchmark-specific module:create_api")
    args = parser.parse_args()
    module, name = args.factory.split(":", 1)
    factory = getattr(importlib.import_module(module), name)
    write_json(args.response, execute(read_json(args.request), factory))


if __name__ == "__main__":
    main()

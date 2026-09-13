"""One candidate/task attempt per interpreter, preserving partial outputs on failure."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from mm_harness.core.artifacts import digest, read_json, write_json
from mm_harness.core.schema import Outcome, Task
from mm_harness.runtimes.model import ChatModel, ModelError

from .adapter import GenerationAPI


def main():
    request = read_json(Path(sys.argv[1]))
    task = Task(**request["task"])
    directory = Path(request["directory"])
    api = GenerationAPI(
        request["config"],
        ChatModel(request["provider"], request["role"]),
        task,
        request["version"],
        request["repetition"],
        directory,
        Path(request["harness_path"]),
    )
    start = time.monotonic()
    score, metrics, error = None, {}, None
    try:
        path = Path(request["harness_path"]) / "harness.py"
        spec = importlib.util.spec_from_file_location("candidate_harness", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        html = module.run(api)
        if html != api.current_html:
            raise ValueError("Candidate returned HTML different from its final rendered artifact")
        status = "success"
    except ModelError as exc:
        status, error = "model_error", str(exc)
    except Exception as exc:
        status, error = "environment_error", f"{type(exc).__name__}: {exc}"
    api.cost.wall_seconds = time.monotonic() - start
    outcome = Outcome(
        task.task_id,
        request["version"],
        task.split,
        request["repetition"],
        status,
        score,
        metrics,
        api.cost,
        digest(request["config"]),
        str(directory),
        error,
    )
    write_json(directory / "generation-outcome.json", outcome.to_dict())
    print(status, score, error or "", flush=True)


if __name__ == "__main__":
    main()

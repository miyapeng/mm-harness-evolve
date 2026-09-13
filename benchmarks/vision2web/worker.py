import importlib.util
import sys
from pathlib import Path

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.runtimes.process import run_process


class API:
    def __init__(self, request):
        self.request, self.prompt = request, request["prompt"]

    def execute_openhands(self, prompt):
        return run_process(
            [
                sys.executable,
                "-m",
                "benchmarks.vision2web.openhands_entrypoint",
                "--headless",
                "--json",
                "--override-with-envs",
                "-t",
                prompt,
            ],
            cwd=Path(self.request["workspace"]),
            directory=Path(self.request["directory"]) / "agent",
            timeout=self.request["timeout"],
        )


request = read_json(Path(sys.argv[1]))
spec = importlib.util.spec_from_file_location("candidate_harness", request["harness"])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.run(API(request))
write_json(Path(request["directory"]) / "generation-process.json", result)

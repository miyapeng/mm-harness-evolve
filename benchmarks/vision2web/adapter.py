"""Local generation integration. Full official container scoring remains a separate command."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from mm_harness.core.artifacts import digest, read_json, write_json
from mm_harness.core.media import copy_media
from mm_harness.core.schema import Cost, Outcome
from mm_harness.core.store import Trace
from mm_harness.runtimes.process import run_process


class Vision2WebAdapter:
    def __init__(self, config, model):
        self.config, self.model = config, model
        self.fingerprint = digest(config)

    def run(self, task, harness_path, version, repetition, directory):
        source = Path(task.payload["source_dir"])
        workspace = directory / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        for name in ("prototypes", "resources"):
            if (source / name).is_dir():
                shutil.copytree(source / name, workspace / name)
        for name in ("prompt.txt", "prd.md"):
            if (source / name).is_file():
                shutil.copy2(source / name, workspace / name)
        trace = Trace(directory, task.task_id, version)
        trace.add(
            "task_input",
            media=[
                copy_media(p, directory, "reference")
                for p in sorted((workspace / "prototypes").iterdir())
                if p.suffix.lower() in (".png", ".jpg", ".jpeg")
            ],
            protocol="released_inputs_only; local_workspace_path_translation",
        )
        config = self.config
        root = Path(__file__).resolve().parents[2]
        prompt = (harness_path / "prompt.txt").read_text().replace("/workspace", str(workspace))
        (directory / "task-prompt.txt").write_text(prompt)
        proxy_config = {
            "base_url": self.model.provider["base_url"],
            "role": self.model.role,
            "max_calls": config["max_model_calls"],
        }
        write_json(directory / "proxy-config.json", proxy_config)
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)]),
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "http_proxy": "",
                "https_proxy": "",
                "NO_PROXY": "*",
                "no_proxy": "*",
            }
        )
        proxy = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mm_harness.runtimes.audit_proxy",
                "--config",
                str(directory / "proxy-config.json"),
                "--output",
                str(directory / "model"),
            ],
            env=env,
            start_new_session=True,
        )
        started = time.monotonic()
        try:
            ready = directory / "model/ready.json"
            for _ in range(100):
                if ready.exists():
                    break
                if proxy.poll() is not None:
                    raise RuntimeError("Model gateway exited")
                time.sleep(0.1)
            endpoint = read_json(ready)["base_url"]
            env.update(
                {
                    "LLM_MODEL": f"litellm_proxy/{self.model.role['model']}",
                    "LLM_API_KEY": "EMPTY",
                    "LLM_BASE_URL": endpoint,
                    "PERSISTENCE_DIR": str(directory / "openhands-state"),
                    "MM_HARNESS_EXTENSIONS": config["extensions"],
                    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                    "PYTHONPATH": os.pathsep.join(
                        [config["openhands_src"], str(root / "src"), str(root)]
                    ),
                    "PATH": os.pathsep.join([str(Path(config["python"]).parent), env["PATH"]]),
                }
            )
            # Candidate Python is loaded in a new worker, with only the explicit generation API.
            request = {
                "prompt": prompt,
                "workspace": str(workspace),
                "directory": str(directory),
                "harness": str(harness_path / "harness.py"),
                "timeout": config["timeout_seconds"],
            }
            write_json(directory / "worker-request.json", request)
            process = run_process(
                [
                    config["python"],
                    "-m",
                    "benchmarks.vision2web.worker",
                    str(directory / "worker-request.json"),
                ],
                cwd=workspace,
                directory=directory / "worker",
                timeout=config["timeout_seconds"] + 10,
                env=env,
            )
            cost = Cost(wall_seconds=time.monotonic() - started)
            for call in sorted((directory / "model").glob("call-*")):
                cost.model_calls += 1
                req = read_json(call / "request.json")
                n = sum(
                    b.get("type") == "image_url"
                    for m in req.get("messages", [])
                    if isinstance(m.get("content"), list)
                    for b in m["content"]
                )
                cost.visual_observations += n
                trace.add(
                    "model_request",
                    request=str((call / "request.json").relative_to(directory)),
                    image_blocks=n,
                )
                raw_path = call / "response.raw"
                if raw_path.exists():
                    raw = raw_path.read_text()
                    try:
                        response = json.loads(raw)
                        usage = response.get("usage", {})
                        cost.input_tokens += usage.get("prompt_tokens", 0)
                        cost.output_tokens += usage.get("completion_tokens", 0)
                    except json.JSONDecodeError:
                        trace.add(
                            "usage_unavailable",
                            reason="SSE response requires usage stream aggregation",
                        )
            log = directory / "agent/stdout.log"
            if log.exists():
                for line in log.read_text().splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("kind") == "ActionEvent":
                        cost.tool_calls += 1
                    trace.add("openhands_event", event=event)
            status = "timeout" if process["status"] == "timeout" else "unscored"
            error = "Full official evaluator not executed; generation artifacts retained"
            write_json(
                directory / "generation-status.json",
                {
                    "start_sh_exists": (workspace / "start.sh").exists(),
                    "process": process,
                    "official_scoring": False,
                    "cost": cost.__dict__,
                },
            )
            return Outcome(
                task.task_id,
                version,
                task.split,
                repetition,
                status,
                None,
                {},
                cost,
                self.fingerprint,
                str(directory),
                error,
            )
        finally:
            try:
                os.killpg(proxy.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            proxy.wait()

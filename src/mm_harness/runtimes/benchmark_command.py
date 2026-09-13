"""File-based bridge to benchmark-owned Python environments, containers and services.

Commands are argv arrays, never shell templates. The execution worker receives only
agent inputs; the scoring worker receives private inputs after execution ends.
Filesystem/service isolation is supplied by the configured runtime, not by this bridge.
"""

from __future__ import annotations

import os
import time

from mm_harness.core.artifacts import contained, digest, file_digest, read_json, write_json
from mm_harness.core.media import copy_media
from mm_harness.core.schema import Cost, Outcome
from mm_harness.core.store import Trace
from mm_harness.runtimes.process import run_process


class BenchmarkNotConfigured(ValueError):
    pass


class CommandBenchmarkAdapter:
    benchmark = ""

    def __init__(self, config: dict, model):
        self.config, self.model = config, model
        self.fingerprint = digest(config)

    def _stage(self, stage, request, directory, timeout):
        command = self.config.get("commands", {}).get(stage)
        if not command:
            raise BenchmarkNotConfigured(f"{self.benchmark}: commands.{stage} is not configured")
        request_path, response_path = directory / "request.json", directory / "response.json"
        write_json(request_path, request)
        values = {"request": str(request_path), "response": str(response_path)}
        argv = [part.format_map(values) for part in command]
        process = run_process(
            argv,
            cwd=directory,
            directory=directory / "process",
            timeout=timeout,
            env={**os.environ, **self.config.get("environment", {})},
        )
        write_json(directory / "process.json", process)
        if process["status"] == "timeout":
            raise TimeoutError(f"{stage} timed out")
        if process["returncode"] != 0 or not response_path.exists():
            raise RuntimeError(f"{stage} worker failed; inspect {directory / 'process'}")
        response = read_json(response_path)
        for key in ("task_id", "harness_id", "repetition"):
            if response.get(key) != request[key]:
                raise ValueError(f"{stage} response {key} mismatch")
        return response

    def run(self, task, harness_path, version, repetition, directory):
        if task.benchmark != self.benchmark:
            raise ValueError("Adapter/task benchmark mismatch")
        for stage in ("execute", "score"):
            if not self.config.get("commands", {}).get(stage):
                raise BenchmarkNotConfigured(f"{self.benchmark}: configure commands.{stage} first")
        directory = directory.resolve()
        workspace = directory / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        files = {name: (harness_path / name).read_text() for name in ("harness.py", "prompt.txt")}
        if "sha256:" + digest(files) != version:
            raise ValueError("Candidate files do not match requested harness version")
        trace = Trace(directory, task.task_id, version)
        identity = {"task_id": task.task_id, "harness_id": version, "repetition": repetition}
        actor_inputs = task.payload.get("agent_input", {})
        request = {
            "schema_version": "mm_harness/execute/v1",
            **identity,
            "benchmark": self.benchmark,
            "workspace": str(workspace),
            "agent_input": actor_inputs,
            "harness": {"files": files, "path": str(harness_path.resolve())},
            "provider": self.model.provider,
            "role": self.model.role,
            "protocol": self.config["protocol"],
            "execution_components": self.config.get("execution_components", {}),
        }
        trace.add("task_input", agent_input=actor_inputs, protocol=self.config["protocol"])
        cost, metrics, score, error = Cost(), {}, None, None
        started = time.monotonic()
        status = "environment_error"
        try:
            # A preparation worker must finish after a reset. Container/service lifetime is
            # managed externally; a daemon spawned by a stage is cleaned up by run_process.
            if self.config.get("commands", {}).get("prepare"):
                self._stage(
                    "prepare", request, directory / "prepare", self.config["timeout_seconds"]
                )
            execution = self._stage(
                "execute", request, directory / "execute", self.config["timeout_seconds"]
            )
            cost = Cost(**execution["cost"])
            status = execution["status"]
            if status not in (
                "success",
                "task_failure",
                "model_error",
                "environment_error",
                "timeout",
            ):
                raise ValueError(f"Unknown execution status: {status}")
            for event in execution.get("events", []):
                media = []
                for item in event.get("media", []):
                    source = contained(workspace, item["path"])
                    if item.get("sha256") and file_digest(source) != item["sha256"]:
                        raise ValueError("Worker media digest mismatch")
                    media.append(
                        copy_media(source, directory, item["role"], source_event=event["event_id"])
                    )
                trace.add(
                    event["kind"],
                    media=media,
                    source_event_id=event["event_id"],
                    native_payload=event.get("payload", {}),
                )
            artifacts = []
            for value in execution.get("artifacts", []):
                path = contained(workspace, value["path"])
                artifacts.append({**value, "path": str(path), "sha256": file_digest(path)})
            write_json(directory / "artifacts.json", artifacts)
            # Model errors and environment errors are not silently scored as task failures.
            if status in ("success", "task_failure"):
                scoring = {
                    "schema_version": "mm_harness/score/v1",
                    **identity,
                    "benchmark": self.benchmark,
                    "artifacts": artifacts,
                    "evaluator_input": task.payload.get("evaluator_input", {}),
                    "evaluator": self.config["evaluator"],
                    "evaluator_id": self.fingerprint,
                }
                result = self._stage(
                    "score",
                    scoring,
                    directory / "score",
                    self.config.get("score_timeout_seconds", 600),
                )
                if result["evaluator_id"] != self.fingerprint:
                    raise ValueError("Scorer identity mismatch")
                status, score, metrics = result["status"], result["score"], result["metrics"]
                trace.add(
                    "evaluation",
                    metrics=metrics,
                    score=score,
                    evaluator_id=self.fingerprint,
                    evaluator_cost=result.get("cost"),
                    components=self.config["evaluator"],
                )
                write_json(directory / "evaluator-cost.json", result.get("cost"))
            error = execution.get("error")
        except TimeoutError as exc:
            status, error = "timeout", str(exc)
        except Exception as exc:
            status, error, score = "environment_error", f"{type(exc).__name__}: {exc}", None
        finally:
            if self.config.get("commands", {}).get("cleanup"):
                try:
                    self._stage("cleanup", request, directory / "cleanup", 120)
                except Exception as exc:
                    trace.add("cleanup_error", error=str(exc))
                    status, score, error = "environment_error", None, f"cleanup failed: {exc}"
            cost.wall_seconds = time.monotonic() - started
        outcome = Outcome(
            task.task_id,
            version,
            task.split,
            repetition,
            status,
            score,
            metrics,
            cost,
            self.fingerprint,
            str(directory),
            error,
        )
        write_json(directory / "outcome.json", outcome.to_dict())
        return outcome

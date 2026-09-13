from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

from mm_harness.core.artifacts import digest, file_digest, read_json, write_json
from mm_harness.core.media import copy_media
from mm_harness.core.schema import Cost, Outcome
from mm_harness.core.store import Trace
from mm_harness.runtimes.model import ModelError
from mm_harness.runtimes.process import run_process


class Design2CodeAdapter:
    def __init__(self, config, model):
        self.config, self.model = config, model
        self.fingerprint = digest(config)

    def run(self, task, harness_path, version, repetition, directory):
        started = time.monotonic()
        # Execute candidate Python in a new process so changed modules never use import caches.
        request = {
            "config": self.config,
            "provider": self.model.provider,
            "role": self.model.role,
            "task": asdict(task),
            "harness_path": str(harness_path),
            "version": version,
            "repetition": repetition,
            "directory": str(directory),
        }
        write_json(directory / "worker-request.json", request)
        env = os.environ.copy()
        root = Path(__file__).resolve().parents[3]
        env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), str(root)])
        result = run_process(
            [
                sys.executable,
                "-m",
                "benchmarks.design2code.worker",
                str(directory / "worker-request.json"),
            ],
            cwd=root,
            directory=directory / "worker",
            timeout=self.config["timeout_seconds"],
            env=env,
        )
        write_json(directory / "worker-process.json", result)
        if (directory / "generation-outcome.json").exists():
            outcome = Outcome.from_dict(read_json(directory / "generation-outcome.json"))
            if outcome.status in ("success", "task_failure"):
                try:
                    metrics = score_artifact(self.config, task, repetition, directory)
                    outcome.metrics, outcome.score = metrics, metrics["score"]
                    outcome.status = (
                        "success"
                        if outcome.score >= self.config["success_threshold"]
                        else "task_failure"
                    )
                    Trace(directory, task.task_id, version).add(
                        "evaluation", metrics=metrics, evaluator_id=self.fingerprint
                    )
                except Exception as exc:
                    outcome.status, outcome.score = "environment_error", None
                    outcome.error = str(exc)
            outcome.cost.wall_seconds = time.monotonic() - started
            write_json(directory / "outcome.json", outcome.to_dict())
            return outcome
        return Outcome(
            task.task_id,
            version,
            task.split,
            repetition,
            "timeout" if result["status"] == "timeout" else "environment_error",
            None,
            {},
            Cost(wall_seconds=result["seconds"]),
            self.fingerprint,
            str(directory),
            "Worker did not produce a complete outcome; inspect worker logs",
        )


class GenerationAPI:
    def __init__(self, config, model, task, version, repetition, directory, harness_path):
        self.config, self.model, self.task = config, model, task
        self.root, self.repetition = directory, repetition
        self.trace = Trace(directory, task.task_id, version)
        self.cost = Cost()
        self.prompt = (harness_path / "prompt.txt").read_text()
        self.reference_image = {"path": task.payload["image"], "role": "reference"}
        expected = task.payload.get("image_sha256")
        if expected and file_digest(Path(self.reference_image["path"])) != expected:
            raise ValueError("Task reference image changed since split freeze")
        self.workspace = directory / "workspace"
        self.workspace.mkdir(exist_ok=True)
        shutil.copy2(config["placeholder"], self.workspace / "rick.jpg")
        ref = copy_media(Path(self.reference_image["path"]), directory, "reference")
        self.trace.add(
            "task_input",
            media=[ref],
            prompt=self.prompt,
            protocol="image_only_no_reference_html_or_extracted_text",
        )

    def generate(self, prompt, images):
        if self.cost.model_calls >= self.config["max_model_calls"]:
            raise ModelError("Executor exceeded fixed model-call budget")
        call = self.cost.model_calls
        self.cost.model_calls += 1
        response = self.model.call(
            prompt,
            images,
            self.root / "model" / f"call-{call}",
            seed=self.config["seed"] + self.repetition,
        )
        usage = response["usage"]
        self.cost.input_tokens += usage.get("prompt_tokens", 0)
        self.cost.output_tokens += usage.get("completion_tokens", 0)
        self.cost.visual_observations += response["images"]
        html = response["text"].strip()
        match = re.search(r"```(?:html)?\s*([\s\S]*?)```", html)
        if match:
            html = match[1].strip()
        start = re.search(r"<!doctype|<html", html, re.I)
        if start:
            html = html[start.start() :]
        if not re.search(r"<html|<!doctype", html, re.I):
            raise ModelError("Model did not return an HTML document")
        artifact = self.root / f"generated-{call}.html"
        artifact.write_text(html)
        self.trace.add(
            "generation",
            prompt=prompt,
            code=html,
            code_sha256=file_digest(artifact),
            request=f"model/call-{call}/request.json",
            image_count=len(images),
            usage=usage,
        )
        return html

    def render(self, html):
        count = self.cost.tool_calls
        self.cost.tool_calls += 1
        self.current_html = html
        (self.workspace / "index.html").write_text(html)
        target = self.root / f"render-{count}.png"
        task = {
            "result": {"task_id": self.task.task_id},
            "htmlPath": str(self.workspace / "index.html"),
            "outputPath": str(target),
            "sitePath": True,
            "width": 1280,
            "height": 720,
            "fullPage": True,
            "waitMs": 1000,
            "timeoutMs": 60000,
        }
        write_json(self.root / f"render-{count}.json", [task])
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = self.config["browsers_path"]
        result = run_process(
            [
                self.config["node"],
                self.config["renderer"],
                self.config["driver"],
                str(self.root / f"render-{count}.json"),
                "1",
            ],
            cwd=self.workspace,
            directory=self.root / f"render-{count}-process",
            timeout=90,
            env=env,
        )
        if result["returncode"] or not target.exists():
            raise RuntimeError("Browser render failed; see render process logs")
        code_sha256 = file_digest(self.workspace / "index.html")
        media = copy_media(target, self.root, "generated", code_sha256=code_sha256)
        self.trace.add(
            "render",
            media=[media],
            tool="chromium",
            result=result,
            code_sha256=code_sha256,
            html_artifact="workspace/index.html",
        )
        return {"path": str(target), "role": "current_render", "sha256": file_digest(target)}


def score_artifact(config, task, repetition, root):
    # The trusted scorer alone loads reference HTML, after generation finishes.
    private = root / "scorer-private"
    private.mkdir(exist_ok=True)
    with Path(config["dataset_file"]).open() as handle:
        row = next(r for r in map(json.loads, handle) if str(r["id"]) == task.task_id)
    (private / "reference.html").write_text(row["reference"])
    shutil.copy2(config["placeholder"], private / "rick.jpg")
    manifest = [
        {
            "key": task.task_id,
            "item_id": task.task_id,
            "sample_index": repetition,
            "prediction_html": str(root / "workspace" / "index.html"),
            "reference_html": str(private / "reference.html"),
        }
    ]
    write_json(private / "manifest.json", manifest)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = config["browsers_path"]
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["OMP_NUM_THREADS"] = "2"
    env["PYTHONPATH"] = config["legacy_src"]
    env["MM_HARNESS_CACHE"] = config["cache_root"]
    result = run_process(
        [
            config["eval_python"],
            str(Path(__file__).with_name("score_worker.py")),
            "--upstream-root",
            config["evaluator_root"],
            "--manifest",
            str(private / "manifest.json"),
            "--output",
            str(private / "scores.json"),
        ],
        cwd=private,
        directory=private / "process",
        timeout=360,
        env=env,
    )
    if result["returncode"] or not (private / "scores.json").exists():
        raise RuntimeError("Official Design2Code scorer failed; inspect scorer-private/process")
    score = read_json(private / "scores.json")["rows"][0]
    if score["status"] != "ok":
        raise RuntimeError(score.get("error", "Scorer failed"))
    return score

"""Durable native SWE-agent -> fresh official instance scoring worker.

Remote jobs yield Pending; invoking the search again reuses completed jobs of
this sampling identity. A new round receives a different sampling identity.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from mm_harness.core.artifacts import digest, file_digest, read_json, write_json
from mm_harness.evolution.minibatch import Pending

ROOT = Path(__file__).resolve().parents[2]
CLUSTERX = "/data/miyapeng/persistent/bin/clusterx"
PYTHON = ROOT / ".venv-swe-worker/bin/python"


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def remote(arguments):
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    return subprocess.run(
        [CLUSTERX, *arguments], env=env, text=True, capture_output=True, timeout=120
    )


def job(attempt, stage, image, command):
    record = attempt / f"{stage}-job.json"
    name = "mmhe-" + stage + "-" + digest(str(attempt.resolve()))[:16]
    if record.exists():
        result = remote(["get-job", name, "--no-verbose"])
        if result.returncode:
            raise Pending(f"Cannot query {name}: {result.stderr[-600:]}")
        match = re.search(r"JobStatus\.(\w+)", result.stdout)
        status = match.group(1) if match else "UNKNOWN"
        if status in {"FAILED", "STOPPED", "SUCCEEDED"}:
            return status
        raise Pending(f"{name}: {status}")
    script = attempt / f"{stage}-job.sh"
    # No caller's credentials or environment variables enter the task container.
    env = {
        "PYTHONPATH": f"{ROOT}/src:{ROOT}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "MM_HARNESS_FRESH_SCORER": "1",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }
    shell = "exec env " + " ".join(shlex.quote(k + "=" + v) for k, v in env.items())
    script.write_text(
        "#!/bin/bash\nset -eu\ncd "
        + shlex.quote(str(ROOT))
        + "\n"
        + shell
        + " "
        + shlex.join(command)
        + "\n"
    )
    # Persist intent before network submission. An interrupted submission is
    # queried under the same deterministic name, never silently duplicated.
    write_json(record, {"name": name, "image": image, "command": command, "status": "submitting"})
    result = remote(
        [
            "run",
            "--job-name",
            name,
            "--num-nodes",
            "1",
            "--gpus-per-task",
            "0",
            "--cpus-per-task",
            "4",
            "--memory-per-task",
            "16",
            "--shm-size-gib",
            "2",
            "--no-env",
            "--image",
            image,
            "bash",
            str(script),
        ]
    )
    (attempt / f"{stage}-submit.log").write_text(result.stdout + result.stderr)
    write_json(
        record,
        {
            "name": name,
            "image": image,
            "command": command,
            "returncode": result.returncode,
            "status": "submitted" if not result.returncode else "submission_error",
        },
    )
    raise Pending(f"{name}: submitted; resume after completion")


def stage_issue_image(image, path, directory):
    """Keep raw bytes; adapt GIFs to three fixed frames for official image loading."""
    target = directory / path.name
    shutil.copyfile(path, target)
    base = {"url": image["url"], "source_sha256": image["sha256"], "raw_filename": target.name}
    if image["content_type"].split(";")[0] != "image/gif":
        return [{**base, "filename": target.name, "sha256": image["sha256"]}]
    from PIL import Image

    with Image.open(path) as gif:
        indices = {0, (gif.n_frames - 1) // 2, gif.n_frames - 1}
        selected = []
        timestamp_ms = 0
        for index in range(gif.n_frames):
            gif.seek(index)
            if index in indices:
                frame = directory / f"{image['sha256']}-frame-{index:04}.png"
                gif.convert("RGB").save(frame)
                selected.append(
                    {
                        **base,
                        "filename": frame.name,
                        "sha256": file_digest(frame),
                        "frame_index": index,
                        "timestamp_ms": timestamp_ms,
                        "frame_count": gif.n_frames,
                        "selection": "fixed_first_middle_last",
                    }
                )
            timestamp_ms += gif.info.get("duration", 0)
    return selected


def prepare(identity, source, attempt):
    experiment_path = next(
        (
            parent / "experiment.json"
            for parent in attempt.parents
            if (parent / "experiment.json").is_file()
        ),
        None,
    )
    if experiment_path is None:
        raise ValueError("Prepare an experiment before starting native workers")
    roles = read_json(experiment_path)["roles"]
    service = read_json(ROOT / roles["provider"]["service_ready"])
    instance = next(
        r
        for r in rows(ROOT / "data/swe_mm/dev/agent_visible/sweagent-instances.jsonl")
        if r["instance_id"] == identity["task_id"]
    )
    images = {r["url"]: r for r in rows(ROOT / "data/swe_mm/dev/image_manifest.jsonl")}
    public = attempt / "input/images"
    public.mkdir(parents=True, exist_ok=True)
    selected = []
    for url in instance["extra_fields"]["issue_images"]:
        image = images[url]
        path = ROOT / "data/swe_mm/dev" / image["local_path"]
        if file_digest(path) != image["sha256"]:
            raise ValueError("Issue image content drift")
        selected.extend(stage_issue_image(image, path, public))
    spec = {
        "identity": identity,
        "source": str(source.resolve()),
        "instance": instance,
        "role": roles["actor"],
        "base_url": service["endpoint"],
        "service_ready": service,
        "issue_images": selected,
    }
    write_json(attempt / "actor-request.json", spec)
    return spec


def export(identity, attempt, actor, report):
    rollout = attempt / "rollout"
    events = []
    input_tokens = output_tokens = image_presentations = requested_tool_calls = 0
    unique_images = set()
    unreported_requests = 0
    for index, call in enumerate(sorted((rollout / "requests").glob("call-*"))):
        body = read_json(call / "request.json")
        events.append(
            {
                **identity,
                "event_id": f"model-request-{index:04}",
                "kind": "model_request",
                "request_id": str(call.resolve()),
                "payload": body,
            }
        )
        for message in body.get("messages", []):
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url":
                        image_presentations += 1
                        unique_images.add(digest(part["image_url"]))
        audit_path = call / "media-audit.json"
        if audit_path.exists():
            audit = read_json(audit_path)
            for item_index, artifact in enumerate(audit["artifacts"]):
                artifact = dict(artifact)
                artifact["storage_ref"] = str((call / artifact["storage_ref"]).relative_to(rollout))
                events.append(
                    {
                        **identity,
                        "event_id": f"request-artifact-{index:04}-{item_index}",
                        "kind": "media_artifact",
                        "payload": {"role": "A", "stage": "persist", "artifact": artifact},
                        "media": [
                            {
                                "path": artifact["storage_ref"],
                                "sha256": artifact["content_hash"],
                                "mime_type": artifact["metadata"]["mime_type"],
                            }
                        ],
                    }
                )
            for item_index, use in enumerate(audit["uses"]):
                events.append(
                    {
                        **identity,
                        "event_id": f"request-use-{index:04}-{item_index}",
                        "kind": "media_use",
                        "payload": {"role": "A", "use": use},
                    }
                )
        response_path = call / "response.raw"
        if response_path.exists():
            response = json.loads(response_path.read_text())
            usage = response.get("usage") or {}
            input_tokens += usage.get("prompt_tokens", 0)
            output_tokens += usage.get("completion_tokens", 0)
            requested_tool_calls += sum(
                len(c.get("message", {}).get("tool_calls") or [])
                for c in response.get("choices", [])
            )
            events.append(
                {
                    **identity,
                    "event_id": f"model-response-{index:04}",
                    "kind": "model_response",
                    "payload": response,
                }
            )
        else:
            unreported_requests += 1
    trajectory = read_json(rollout / actor["trajectory"]) if actor.get("trajectory") else {}
    for index, step in enumerate(trajectory.get("trajectory", [])):
        events.append(
            {**identity, "event_id": f"tool-step-{index:04}", "kind": "tool_step", "payload": step}
        )
    (rollout / "events.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    )
    tool_calls = sum(bool(step.get("action")) for step in trajectory.get("trajectory", []))
    status = report.get("status", "success" if report.get("resolved") else "task_failure")
    result = {
        **identity,
        "rollout": str(rollout),
        "status": status,
        "score": float(bool(report.get("resolved")))
        if status in {"success", "task_failure"}
        else None,
        "feedback": {
            "resolved": bool(report.get("resolved")),
            "exit_status": actor.get("exit_status"),
            "scoring_status": report.get("scoring_status", "official_tests"),
        },
        "cost": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "seconds": actor["seconds"],
            "tool_calls": tool_calls,
            "requested_tool_calls": requested_tool_calls,
            "model_calls": len(list((rollout / "requests").glob("call-*"))),
            "unique_images": len(unique_images),
            "scorer_seconds": report.get("scorer_seconds", 0),
            "gpu_seconds": None,
            "unreported_requests": unreported_requests,
            "token_accounting": "lower_bound" if unreported_requests else "complete",
            "image_presentations": image_presentations,
            "usd": None,
        },
        "evidence_files": [],
    }
    for path, kind, format_ in [
        ("prediction.patch", "artifact", "text"),
        (actor.get("trajectory"), "tool_log", "json"),
    ]:
        if path and (rollout / path).is_file():
            result["evidence_files"].append(
                {
                    "path": path,
                    "kind": kind,
                    "format": format_,
                    "visibility": "evolver",
                    "sha256": file_digest(rollout / path),
                }
            )
    write_json(attempt / "result.json", result)
    return result


def run_and_score(identity, frozen_source_path, attempt_dir):
    attempt = attempt_dir.resolve()
    attempt.mkdir(parents=True, exist_ok=True)
    request = attempt / "actor-request.json"
    spec = (
        read_json(request) if request.exists() else prepare(identity, frozen_source_path, attempt)
    )
    if spec["identity"] != identity or Path(spec["source"]) != frozen_source_path.resolve():
        raise ValueError("Worker resume identity/source differs")
    if (attempt / "result.json").exists():
        return read_json(attempt / "result.json")
    actor_result = attempt / "rollout/actor-result.json"
    if not actor_result.exists():
        status = job(
            attempt,
            "actor",
            spec["instance"]["image_name"],
            [str(PYTHON), "-m", "benchmarks.swe_mm.actor_worker", "--request", str(request)],
        )
        if not actor_result.exists():
            raise RuntimeError(f"Actor job ended {status} without result; inspect {attempt}")
    actor = read_json(actor_result)
    if actor["identity"] != identity:
        raise ValueError("Actor result identity mismatch")
    if not actor.get("trajectory"):
        raise RuntimeError(
            f"Native actor failed before a trajectory; inspect {attempt}/rollout/process"
        )
    if any(
        reason in (actor.get("exit_status") or "")
        for reason in ("exit_api", "exit_environment_error", "exit_error")
    ):
        if not (attempt / "rollout/requests/budget-exhausted.json").exists():
            return export(
                identity,
                attempt,
                actor,
                {
                    "status": "environment_error",
                    "resolved": False,
                    "scoring_status": actor["exit_status"],
                },
            )
    patch = attempt / "rollout/prediction.patch"
    if not patch.read_text().strip():
        return export(
            identity, attempt, actor, {"resolved": False, "scoring_status": "no_submission"}
        )
    score_dir = attempt / "scorer-private" / identity["task_id"]
    report_path = score_dir / "report.json"
    if not (score_dir / "complete.json").exists():
        status = job(
            attempt,
            "score",
            spec["instance"]["image_name"],
            [
                "/data/miyapeng/miniconda3/envs/swemm/bin/python",
                str(ROOT / "benchmarks/swe_mm/score_worker.py"),
                "--instance-id",
                identity["task_id"],
                "--patch",
                str(patch),
                "--output-root",
                str(attempt / "scorer-private"),
            ],
        )
        if not (score_dir / "complete.json").exists():
            raise RuntimeError(f"Scorer job ended {status} without report; inspect {score_dir}")
    complete = read_json(score_dir / "complete.json")
    if complete["instance_id"] != identity["task_id"] or complete["report_sha256"] != file_digest(
        report_path
    ):
        raise ValueError("Scorer completion identity/report differs")
    report = read_json(report_path)[identity["task_id"]]
    metadata = read_json(score_dir / "metadata.json")
    report["scorer_seconds"] = (
        datetime.fromisoformat(metadata["finished_at_utc"])
        - datetime.fromisoformat(metadata["started_at_utc"])
    ).total_seconds()
    if metadata["timed_out"]:
        report = {**report, "status": "environment_error", "scoring_status": "scorer_timeout"}
    return export(identity, attempt, actor, report)

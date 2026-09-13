"""ClusterX instance entry point for the selected native SWE-agent harness.

The fresh instance supplies /testbed and Node/browser dependencies. Only public
inputs, selected source, runtime libraries and this attempt's output are mounted
into the task root. The model gateway retains actual transmitted image bodies.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mm_harness.core.artifacts import read_json, write_json
from mm_harness.runtimes.audit_proxy import serve
from mm_harness.runtimes.process import run_process

ROOT = Path(__file__).resolve().parents[2]
PYBASE = Path("/data/miyapeng/miniconda3/envs/vllm")


def execute(request_path: Path) -> None:
    spec = read_json(request_path)
    attempt = request_path.parent
    output = attempt / "rollout"
    output.mkdir(exist_ok=True)
    public = attempt / "input"
    home = attempt / "task-home"
    home.mkdir(exist_ok=True)
    # The upstream tool scripts use this absolute interpreter path. The fixed
    # compatibility launcher supplies Python 3.12 with the pinned tool packages.
    bin_dir = home / "python3.11/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = ROOT / ".venv-swe-worker/bin/python"
    for name in ("python3", "python", "pip", "pip3"):
        target = bin_dir / name
        command = f"exec {python} " + ("-m pip " if name.startswith("pip") else "") + '"$@"\n'
        target.write_text("#!/bin/bash\n" + command)
        target.chmod(0o755)
    (home / ".bashrc").write_text("export PATH=/root/python3.11/bin:" + os.environ["PATH"] + "\n")
    role = spec["role"]
    gateway_config = {
        "base_url": spec["base_url"],
        "max_calls": role["max_requests"],
        "role": {
            **role,
            "timeout_seconds": role["request_timeout_seconds"],
            "extra_body": {
                "top_p": role["top_p"],
                "chat_template_kwargs": {"enable_thinking": role["enable_thinking"]},
            },
        },
    }
    requests = attempt / "audit-private/requests"
    threading.Thread(
        target=serve, args=(gateway_config, requests, requests / "ready.json"), daemon=True
    ).start()
    deadline = time.monotonic() + 10
    while not (requests / "ready.json").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Model gateway did not start")
        time.sleep(0.05)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(public / "images"))
    images = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=images.serve_forever, daemon=True).start()
    instance = json.loads(json.dumps(spec["instance"]))
    instance["extra_fields"]["issue_images"] = [
        f"http://127.0.0.1:{images.server_port}/{item['filename']}" for item in spec["issue_images"]
    ]
    native = {
        **spec,
        "instance": instance,
        "source": "/workspace",
        "output": "/output/native",
        "base_url": read_json(requests / "ready.json")["base_url"] + "/v1",
    }
    write_json(public / "native.json", native)
    binds = [
        [str(spec["source"]), "/workspace", True],
        [str(output), "/output", False],
        [str(public), "/input", True],
        [str(home), "/root", False],
        ["/testbed", "/testbed", False],
        [str(ROOT / "benchmarks/swe_mm/native_actor.py"), "/native_actor.py", True],
        [str(PYBASE), str(PYBASE), True],
        [str(ROOT / ".venv-swe-worker"), str(ROOT / ".venv-swe-worker"), True],
    ]
    for path in ("/usr", "/etc", "/opt", "/root/.nvm", "/root/.cache/ms-playwright"):
        if Path(path).exists():
            binds.append([path, path, True])
    browser_cache = ROOT / ".cache/swe-playwright"
    if browser_cache.exists():
        binds.append([str(browser_cache), str(browser_cache), True])
    env = {
        "PATH": "/root/python3.11/bin:" + os.environ["PATH"],
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "NO_PROXY": "*",
        "no_proxy": "*",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MM_HARNESS_ISOLATED_TASK": "1",
        "PIP_NO_INDEX": "1",
        "PLAYWRIGHT_BROWSERS_PATH": str(browser_cache),
    }
    sandbox = {
        "root": str(attempt / "sandbox-root"),
        "proc_mode": "landlock",
        "binds": binds,
        "env": env,
        "command": [str(python), "/native_actor.py", "--request", "/input/native.json"],
    }
    write_json(attempt / "sandbox.json", sandbox)
    result = run_process(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--mount",
            "--fork",
            str(python),
            str(ROOT / "scripts/sandbox_exec.py"),
            str(attempt / "sandbox.json"),
        ],
        cwd=ROOT,
        directory=output / "process",
        timeout=role["wall_timeout_seconds"],
    )
    shutil.copytree(requests, output / "requests", dirs_exist_ok=False)
    trajectories = list((output / "native").rglob("*.traj"))
    if trajectories:
        trajectory = read_json(trajectories[0])
        submission = trajectory.get("info", {}).get("submission") or ""
        (output / "prediction.patch").write_text(submission)
        result["trajectory"] = str(trajectories[0].relative_to(output))
        result["exit_status"] = trajectory.get("info", {}).get("exit_status")
    else:
        result["trajectory"] = None
    write_json(output / "actor-result.json", {**result, "identity": spec["identity"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    execute(args.request.resolve())


if __name__ == "__main__":
    main()

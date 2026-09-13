"""Start a two-GPU service, retain runtime identity, expire after six hours."""

import hashlib
import importlib.metadata
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

out = Path(sys.argv[1])
model = Path("/data/miyapeng/model/Qwen3.8-27B")
port = 18138
args = [
    sys.executable,
    "-m",
    "vllm.entrypoints.openai.api_server",
    "--model",
    str(model),
    "--served-model-name",
    "Qwen3.8-27B",
    "--host",
    "0.0.0.0",
    "--port",
    str(port),
    "--tensor-parallel-size",
    "2",
    "--max-model-len",
    "131072",
    "--max-num-seqs",
    "2",
    "--gpu-memory-utilization",
    "0.90",
    "--enable-auto-tool-choice",
    "--tool-call-parser",
    "qwen3_coder",
    "--reasoning-parser",
    "qwen3",
    "--no-enable-prefix-caching",
]
record = {
    "model": "Qwen3.8-27B",
    "model_path": str(model),
    "command": args,
    "started_at": time.time(),
    "hostname": socket.gethostname(),
    "vllm": importlib.metadata.version("vllm"),
    "transformers": importlib.metadata.version("transformers"),
    "tensor_parallel_size": 2,
    "max_model_len": 131072,
    "gpu_inventory": subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"], text=True
    ),
    "config_sha256": hashlib.sha256((model / "config.json").read_bytes()).hexdigest(),
    "weight_files": {p.name: p.stat().st_size for p in model.glob("*.safetensors")},
    "identity_limit": "config hash and weight sizes; full checkpoint digest pending",
    "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
(out / "launch.json").write_text(json.dumps(record, indent=2))
opener = build_opener(ProxyHandler({}))
with (out / "vllm.log").open("w") as log:
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def stop(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"vLLM exited {proc.returncode}; inspect vllm.log")
            try:
                with opener.open(f"http://127.0.0.1:{port}/v1/models", timeout=3) as resp:
                    models = json.load(resp)
                ip = subprocess.check_output(["hostname", "-I"], text=True).split()[0]
                (out / "ready.json").write_text(
                    json.dumps(
                        {**record, "endpoint": f"http://{ip}:{port}/v1", "models": models}, indent=2
                    )
                )
                print(f"Ready at http://{ip}:{port}/v1", flush=True)
                break
            except (OSError, ValueError):
                time.sleep(5)
        else:
            raise TimeoutError("vLLM did not become ready in 20 minutes")
        root = Path(__file__).resolve().parents[1]
        probe_env = {**os.environ, "PYTHONPATH": str(root / "src")}
        with (out / "protocol-probe.log").open("w") as probe_log:
            try:
                probe = subprocess.run(
                    [
                        sys.executable,
                        str(root / "scripts/probe_qwen38_service.py"),
                        "--ready",
                        str(out / "ready.json"),
                        "--output",
                        str(out / "protocol-probe"),
                    ],
                    env=probe_env,
                    stdout=probe_log,
                    stderr=subprocess.STDOUT,
                    timeout=400,
                )
                probe_status = {"returncode": probe.returncode}
            except subprocess.TimeoutExpired:
                probe_status = {"status": "timeout"}
        (out / "protocol-probe-status.json").write_text(json.dumps(probe_status))
        try:
            proc.wait(timeout=6 * 3600)
        except subprocess.TimeoutExpired:
            print("Six-hour service lease expired", flush=True)
    finally:
        (out / "stopped.json").write_text(json.dumps({"stopped_at": time.time()}))
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()

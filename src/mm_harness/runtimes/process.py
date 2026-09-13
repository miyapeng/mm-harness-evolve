from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def run_process(
    command: list[str], *, cwd: Path, directory: Path, timeout: float, env: dict | None = None
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (directory / "stdout.log").open("w") as out, (directory / "stderr.log").open("w") as err:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True
        )
        status = "completed"
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            status = "timeout"
        finally:
            # Clean up this invocation's own group, including child servers on normal completion.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    return {
        "command": command,
        "returncode": process.returncode,
        "status": status,
        "seconds": time.monotonic() - started,
    }

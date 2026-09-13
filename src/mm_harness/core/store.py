from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import canonical, digest, read_json, write_json


class RunStore:
    """One controller per run. Completed artifacts are the resume boundary."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / ".controller.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another controller owns this run") from None

    def initialize(self, resolved: dict):
        p = self.root / "resolved.json"
        if p.exists():
            if read_json(p) != resolved:
                raise ValueError("Resume inputs changed; use a new run ID")
        else:
            write_json(p, resolved)
            self.event("initialized", fingerprint=digest(resolved))

    def event(self, kind: str, **payload):
        row = {"kind": kind, "time": datetime.now(timezone.utc).isoformat(), **payload}
        # A separate record per write, followed by fsync; tolerate only a torn final line.
        path = self.root / "events.jsonl"
        with path.open("ab+") as f:
            f.seek(0)
            data = f.read()
            if data and not data.endswith(b"\n"):
                # Preserve the uncommitted tail before completing its line. Readers skip it.
                write_json(
                    self.root / f"interrupted-tail-{digest(data.hex())}.json",
                    {"bytes_hex": data[data.rfind(b"\n") + 1 :].hex()},
                )
                f.write(b"\n")
            f.write((canonical(row) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())

    def close(self):
        self.lock.close()


class Trace:
    def __init__(self, root: Path, task_id: str, harness_id: str):
        self.root, self.task_id, self.harness_id = root, task_id, harness_id
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "events.jsonl"
        self.sequence = len(self.read())

    def read(self):
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]

    def add(self, kind: str, *, media: list[dict] | None = None, **payload):
        self.sequence += 1
        event = {
            "event_id": f"e{self.sequence:05}",
            "task_id": self.task_id,
            "harness_id": self.harness_id,
            "kind": kind,
            "time": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "media": media or [],
        }
        with self.path.open("a") as f:
            f.write(canonical(event) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return event["event_id"]

"""Complete the service's checkpoint identity without loading another model."""

import argparse
import hashlib
from pathlib import Path

from mm_harness.core.artifacts import digest, read_json, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ready", type=Path, required=True)
args = parser.parse_args()
ready = read_json(args.ready)
checkpoint = Path(ready["model_path"])
shards = {}
for name, size in sorted(ready["weight_files"].items()):
    path = checkpoint / name
    before = path.stat()
    if before.st_size != size:
        raise ValueError(f"Checkpoint shard size changed: {name}")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            sha.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError(f"Checkpoint changed during hashing: {name}")
    shards[name] = {
        "sha256": sha.hexdigest(),
        "bytes": size,
        "mtime_precedes_launch": after.st_mtime <= ready["started_at"],
    }
    print(f"{len(shards)}/{len(ready['weight_files'])} shards hashed", flush=True)
manifest = {
    "model": ready["model"],
    "config_sha256": ready["config_sha256"],
    "shards": shards,
    "sha256": digest({name: r["sha256"] for name, r in shards.items()}),
    "scope": "checkpoint bytes on disk; file mtimes compared with service launch",
}
write_json(args.ready.parent / "checkpoint-sha256.json", manifest)
print(manifest["sha256"])

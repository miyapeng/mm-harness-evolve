"""Fetch and verify the pinned Claw-Eval-MM dataset payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

import yaml

BENCHMARK_DIR = Path(__file__).resolve().parents[3] / "benchmarks/claw_eval_mm"
DATA_DIR = BENCHMARK_DIR / "data"
SOURCE_PATH = DATA_DIR / "SOURCE.json"


def _sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(path: Path, *, size_bytes: int, sha256: str) -> None:
    actual_size = path.stat().st_size
    if actual_size != size_bytes:
        raise RuntimeError(f"size mismatch for {path}: expected {size_bytes}, got {actual_size}")
    actual_hash = _sha256(path)
    if actual_hash != sha256:
        raise RuntimeError(f"sha256 mismatch for {path}: expected {sha256}, got {actual_hash}")


def fetch(*, fixtures: bool, metadata: bool) -> list[Path]:
    try:
        from modelscope.hub.file_download import dataset_file_download
    except ImportError as exc:
        raise RuntimeError(
            "Install the acquisition dependency with "
            "`.venv-claw/bin/python -m pip install modelscope==1.40.0`."
        ) from exc

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    selected: list[str] = []
    if fixtures:
        selected.append("data/fixtures.tar.gz")
    if metadata:
        selected.append("data/multimodal-00000-of-00001.parquet")

    downloaded: list[Path] = []
    for relative_path in selected:
        spec = source["files"][relative_path]
        destination = DATA_DIR / relative_path
        if destination.is_file():
            try:
                _verify(destination, **spec)
                print(f"verified existing {destination}")
                downloaded.append(destination)
                continue
            except RuntimeError:
                destination.unlink()

        resolved = Path(
            dataset_file_download(
                source["dataset_id"],
                relative_path,
                revision=source["revision"],
                local_dir=str(DATA_DIR),
            )
        )
        _verify(resolved, **spec)
        print(f"downloaded and verified {resolved}")
        downloaded.append(resolved)
    return downloaded


def materialize(*, upstream_root: Path, force: bool) -> Path:
    """Build a runnable 101-task tree from pinned code plus published fixtures."""
    archive = DATA_DIR / "data/fixtures.tar.gz"
    if not archive.is_file():
        raise RuntimeError(f"fixture archive is missing: {archive}")

    tasks_dir = DATA_DIR / "tasks"
    if tasks_dir.exists():
        if not force:
            raise RuntimeError(
                f"materialized tree already exists: {tasks_dir}; use --force-materialize"
            )
        shutil.rmtree(tasks_dir)
    tasks_dir.mkdir(parents=True)

    selected: set[str] = set()
    for task_yaml in sorted((upstream_root / "tasks").glob("*/task.yaml")):
        task = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))
        if "multimodal" not in task.get("tags", []):
            continue
        selected.add(task_yaml.parent.name)
        shutil.copytree(task_yaml.parent, tasks_dir / task_yaml.parent.name)

    extracted_files = 0
    extracted_bytes = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            parts = Path(member.name).parts
            if not parts or parts[0] not in selected:
                continue
            if Path(member.name).is_absolute() or ".." in parts:
                raise RuntimeError(f"unsafe archive member: {member.name}")
            bundle.extract(member, path=tasks_dir, filter="data")
            if member.isfile():
                extracted_files += 1
                extracted_bytes += member.size

    marker = {
        "code_upstream": str(upstream_root),
        "dataset_revision": json.loads(SOURCE_PATH.read_text())["revision"],
        "selected_tasks": len(selected),
        "extracted_files": extracted_files,
        "extracted_bytes": extracted_bytes,
    }
    (DATA_DIR / "MATERIALIZED.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    print(f"materialized {len(selected)} multimodal tasks at {tasks_dir}")
    return tasks_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="fetch only the 101-row multimodal parquet metadata",
    )
    parser.add_argument(
        "--fixtures-only",
        action="store_true",
        help="fetch only the complete fixture archive",
    )
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="build data/tasks from pinned task definitions and fixture archive",
    )
    parser.add_argument(
        "--force-materialize",
        action="store_true",
        help="replace an existing data/tasks tree when materializing",
    )
    parser.add_argument(
        "--upstream-root",
        type=Path,
        default=BENCHMARK_DIR.parents[1]
        / "third_party/claw-eval-5680b8b11ff2ee5dd2b07b89086a29a5c5c984d7",
        help="pinned official Claw-Eval code checkout",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.metadata_only and args.fixtures_only:
        raise SystemExit("choose at most one of --metadata-only and --fixtures-only")
    fetch(
        fixtures=not args.metadata_only,
        metadata=not args.fixtures_only,
    )
    if args.materialize:
        materialize(upstream_root=args.upstream_root.resolve(), force=args.force_materialize)


if __name__ == "__main__":
    main()

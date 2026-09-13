"""Copy existing benchmark data into this repository; never use external symlinks."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_verified(source, target):
    """Resume an import without overwriting different destination data."""
    records = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name.endswith(".lock"):
            continue
        relative = path.relative_to(source)
        destination = target / relative
        expected = file_hash(path)
        if destination.exists():
            if file_hash(destination) != expected:
                raise ValueError(f"Existing imported data differs: {destination}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            if file_hash(destination) != expected:
                raise ValueError(f"Copy verification failed: {destination}")
        records[str(relative)] = expected
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--benchmark", choices=["swe_mm", "vision2web"], required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    relative = "swe_mm/dev" if args.benchmark == "swe_mm" else "vision2web/extracted"
    source, target = args.legacy / "data" / relative, root / "data" / relative
    if not source.is_dir():
        raise FileNotFoundError(source)
    files = copy_verified(source, target)
    metadata = {}
    if args.benchmark == "vision2web":
        for name in ("manifest.json", "image.json", "instance_ids.txt"):
            original = args.legacy / "data/vision2web" / name
            destination = root / "data/vision2web" / name
            if destination.exists() and destination.read_bytes() != original.read_bytes():
                raise ValueError(f"Existing metadata differs: {destination}")
            destination.write_bytes(original.read_bytes())
            metadata[name] = file_hash(destination)
    manifest = {
        "benchmark": args.benchmark,
        "source": str(source.resolve()),
        "destination": str(target.relative_to(root)),
        "transfer": "independent byte-verified copies, no symlinks",
        "files": files,
        "metadata": metadata,
    }
    manifest_path = target.parent / f"{args.benchmark}-import.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    summary_path = root / "experiments/provenance" / f"{args.benchmark}-data-import.json"
    summary_path.write_text(
        json.dumps(
            {
                **{k: v for k, v in manifest.items() if k != "files"},
                "file_count": len(files),
                "manifest": str(manifest_path.relative_to(root)),
                "manifest_sha256": file_hash(manifest_path),
                "bytes": sum((target / p).stat().st_size for p in files),
            },
            indent=2,
        )
        + "\n"
    )
    print(summary_path.read_text())


if __name__ == "__main__":
    main()

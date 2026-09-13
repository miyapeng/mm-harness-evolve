"""Restore pinned sources without altering an existing checkout or old project."""

import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, help="Optional existing MultimodalCode source root")
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument(
        "--source",
        action="append",
        choices=[
            "AutoSaddler",
            "Meta-Harness",
            "Claw-Eval",
            "SWE-agent",
            "SWE-bench",
            "Vision2Web",
            "AgenticVBench",
            "BrowseComp-V3",
        ],
        help="Restore selected source(s); defaults to the two lightweight evolver sources",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "third_party/lock.json").read_text())
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if args.no_proxy
        else urllib.request.build_opener()
    )
    for name in args.source or ("AutoSaddler", "Meta-Harness"):
        spec = lock["upstreams"][name]
        archive = next(
            (
                p
                for p in (root / "third_party").glob("*.tar.gz")
                if sha(p) == spec["archive_sha256"]
            ),
            None,
        )
        if archive is None:
            archive = root / "third_party" / f"{name}-{spec['commit']}.tar.gz"
            if archive.exists():
                raise ValueError(f"Archive checksum mismatch: {archive}")
            repo = spec["url"].removeprefix("https://github.com/").removesuffix(".git")
            with opener.open(
                f"https://codeload.github.com/{repo}/tar.gz/{spec['commit']}", timeout=60
            ) as response:
                archive.write_bytes(response.read())
        if sha(archive) != spec["archive_sha256"]:
            raise ValueError(f"Downloaded archive checksum mismatch: {archive}")
        target = root / spec["path"]
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                if not member.isfile():
                    continue
                relative = Path(*Path(member.name).parts[1:])
                path = target / relative
                if not path.resolve().is_relative_to(target.resolve()):
                    raise ValueError("Archive member outside target")
                data = source.extractfile(member).read()
                if path.exists():
                    if path.read_bytes() != data:
                        raise ValueError(
                            f"Local source differs; preserve it and choose a separate checkout: {path}"
                        )
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    path.chmod(member.mode & 0o777)
        print(name, spec["commit"], "verified")
    if args.legacy:
        manifest_path = root / "experiments/provenance/legacy-snapshot.json"
        if sha(manifest_path) != lock["local_snapshot"]["manifest_sha256"]:
            raise ValueError("Legacy manifest changed")
        manifest = json.loads(manifest_path.read_text())
        target = root / lock["local_snapshot"]["path"]
        for relative, expected in manifest["files"].items():
            source, dest = args.legacy / relative, target / relative
            if sha(source) != expected:
                raise ValueError(f"Legacy source changed: {source}")
            if dest.exists():
                if sha(dest) != expected:
                    raise ValueError(f"Existing snapshot differs: {dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
        target.mkdir(parents=True, exist_ok=True)
        dest = target / "SNAPSHOT.json"
        if not dest.exists():
            shutil.copy2(manifest_path, dest)
        print("Legacy snapshot", len(manifest["files"]), "files verified")


if __name__ == "__main__":
    main()

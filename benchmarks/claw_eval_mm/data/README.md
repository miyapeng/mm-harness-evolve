# Claw-Eval-MM local data

This directory holds the pinned public Claw-Eval dataset payload used by the
`multimodal` split. Large archives, extracted fixtures, and parquet files are
kept here locally and excluded from Git. `SOURCE.json` is committed so every
checkout retains the exact upstream revision, object sizes, and checksums.

Fetch and verify the published files with:

```bash
.venv-claw/bin/python -m pip install modelscope==1.40.0
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  .venv-claw/bin/python benchmarks/claw_eval_mm/fetch_data.py --materialize
```

The downloader uses the official ModelScope SDK because Hugging Face/Xet is
not reachable from the current development host. It requests an exact dataset
revision and verifies each downloaded byte stream against its Git-LFS object
hash before accepting it.

`fixtures.tar.gz` contains fixtures for all three upstream splits. The
materializer copies the 101 official multimodal task definitions and their
grader files into `data/tasks`, then overlays only their fixture entries. The
original archive remains intact for provenance and recovery.

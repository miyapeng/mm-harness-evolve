# Claw-Eval sandbox image

The canonical sandbox recipe is upstream `Dockerfile.agent` at code commit
`5680b8b11ff2ee5dd2b07b89086a29a5c5c984d7`. Its DaoCloud Python base could
not be reached from this host on 2026-09-09.

`Containerfile.pjlab` is the recorded compatibility build used for the local
registry. It starts from the user's pinned Vision2Web sandbox because that
image is reachable inside the PJLab registry and already contains Python 3.12
and Chromium. The build then installs Claw's declared Python requirements plus
ffmpeg and poppler, copies the exact sandbox server from the pinned source
checkout, and changes no server code. The canonical image uses Python 3.11;
the compatibility image uses Python 3.12 and contains extra Vision2Web packages.
This base substitution is environment setup and must not be reported as harness
evolution.

Build and upload with the existing OCI auth file:

```bash
bash benchmarks/claw_eval_mm/docker/build_and_push.sh /path/to/auth.json
```

The pushed image digest and validation result are recorded in `IMAGE.json`.

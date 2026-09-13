# SWE-MM pilot foundation checks, 2026-09-11

These are implementation checks, not SWE-MM scores or measured harness gains.

- `claude-transport-check.json`: real Claude Code 2.1.49 Read/Write tools, scripted API responses; actual PNG bytes reached the outgoing model request. No Qwen inference.
- `native-source-check.json`: official SWE-agent configuration loaded from a copied H0 source tree. No instance container or task rollout.
- `native-source-check-v2.json`: repeated after implementation commit `59ca9b3`, with the same H0 hash and a 53-file runtime manifest. Configuration loading passed without network/model/container calls.
- Unit/interface suite: 36 passed, including HTTP image forwarding, source versions, candidate patch application and resumable selection.
- GPU model server and CPU image probe remained queued at this milestone; see experiments/provenance/qwen38-service-jobs-2026-09-11.json.

Full local records: runs/claude-fixed-transport-v1 (failed proc mount), runs/claude-fixed-transport-v2 (passed), runs/swe-mm-q38-source-check-v1. The early source check predates this implementation commit; it is not a frozen publication experiment.

# Upstream boundary

Checkouts are ignored by the main repository. Pin source URL, revision, license and local
modifications in lock.json. Never infer a clean source identity from HEAD alone.
AutoSaddler V2 is the engineering integration target; V1 is retained as the paper baseline source.
AutoSaddler and Meta-Harness archives are verified against pinned commits and archive checksums.
Selected legacy code is copied into MultimodalCode (1465 files); the tracked manifest is
../experiments/provenance/legacy-snapshot.json. Dataset files and old Python/browser environments
remain read-only external dependencies. Run ../scripts/bootstrap_sources.py to restore source copies.
No project-wide license overrides upstream code/data terms.

Meta-Harness was also cloned into `meta-harness-git` at pinned commit `44b9942`.
Its unchanged Claude session parser/logger is vendored in
`../src/mm_harness/_vendor/meta_harness/` with MIT LICENSE and SOURCE.json, and is
called by the fixed evolver runtime. See `../docs/PROJECT.md` for the
boundary between upstream logging and our multimodal evidence export.

Claw-Eval is pinned separately for the `claw_eval_mm` benchmark. Restore it explicitly with
`python scripts/bootstrap_sources.py --source Claw-Eval`; its larger archive is not downloaded
by the default lightweight bootstrap/CI. Dataset fixture revision remains a separate setup item.

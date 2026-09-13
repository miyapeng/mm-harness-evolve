"""Fixed Claude Code evolver, scoped to one candidate and supplied evidence.

Run in an isolated filesystem using the existing namespace sandbox. CLI tool
permissions are conveniences, not the boundary separating dev/test data.
"""

from __future__ import annotations

from pathlib import Path

from mm_harness._vendor.meta_harness.claude_wrapper import log_session, parse_stream_events
from mm_harness.core.artifacts import write_json
from mm_harness.runtimes.messages_proxy import messages_gateway
from mm_harness.runtimes.process import run_process


def command(binary: str, role: dict, prompt: str) -> list[str]:
    return [
        binary,
        "--print",
        "--model",
        role["model"],
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(role["max_turns"]),
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--tools",
        "Read,Glob,Grep,Edit,Write,Bash",
        "--allowedTools",
        "Read,Glob,Grep,Edit,Write,Bash",
        "--permission-mode",
        "dontAsk",
        "--append-system-prompt",
        role["system_prompt"],
        prompt,
    ]


def run_claude(root: Path, workspace: Path, role: dict, base_url: str, output: Path) -> dict:
    # The subprocess runs from workspace, not the caller's working directory.
    root, workspace, output = root.resolve(), workspace.resolve(), output.resolve()
    binary = root / ".venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude"
    if not binary.is_file():
        raise FileNotFoundError("Install the pinned claude-agent-sdk evolver extra in .venv")
    output.mkdir(parents=True, exist_ok=True)
    with messages_gateway(base_url, role, output / "requests") as gateway:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/root",
            "LANG": "C.UTF-8",
            "ANTHROPIC_BASE_URL": gateway,
            "ANTHROPIC_API_KEY": "EMPTY",
            "ANTHROPIC_MODEL": role["model"],
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": role["model"],
            "ANTHROPIC_DEFAULT_SONNET_MODEL": role["model"],
            "ANTHROPIC_DEFAULT_OPUS_MODEL": role["model"],
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "DISABLE_PROMPT_CACHING": "1",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(role["max_tokens"]),
            # The pinned CLI otherwise compacts too late for the local 128K service.
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": str(role.get("auto_compact_pct", 40)),
        }
        spec = {
            "root": str(output / "sandbox-root"),
            "proc_mode": "self_only",
            "binds": [
                ["/usr", "/usr", True],
                ["/etc", "/etc", True],
                [str(binary), "/claude", True],
                [str(workspace.resolve()), "/workspace", False],
                *[
                    [str((workspace / name).resolve()), f"/workspace/{name}", True]
                    for name in (
                        "evidence",
                        "history",
                        "history-manifest.json",
                        "overview.json",
                        "WORKSPACE.md",
                        "evidence-manifest.json",
                        "mutation-policy.json",
                        "experiment-context.json",
                        "media-catalog.json",
                    )
                    if (workspace / name).exists()
                ],
            ],
            "command": command(
                "/claude",
                role,
                "Read WORKSPACE.md, overview.json, experiment-context.json and mutation-policy.json "
                "when present. Read history/index.json for prior attempts when available. "
                "Choose evidence to inspect; classify the failure and justify a reusable mechanism. "
                "Write diagnosis.json BEFORE editing source/. Only modify source/ if justified; "
                "write proposal.json linking diagnosis_id, or report no_change.",
            ),
            "env": env,
        }
        write_json(output / "sandbox.json", spec)
        result = run_process(
            [
                "unshare",
                "--user",
                "--map-root-user",
                "--mount",
                "--pid",
                "--fork",
                str(root / ".venv/bin/python"),
                str(root / "scripts/sandbox_exec.py"),
                str(output / "sandbox.json"),
            ],
            cwd=workspace,
            directory=output / "process",
            timeout=role["wall_timeout_seconds"],
        )
    # Keep runtime failures distinct from an intentional no-change proposal.
    write_json(output / "runtime.json", result)
    if result["returncode"] != 0 or result["status"] != "completed":
        raise RuntimeError(f"Claude Code runtime failed; inspect {output}")
    session = parse_stream_events(
        (output / "process/stdout.log").read_text(),
        prompt=spec["command"][-1],
        model=role["model"],
        duration=result["seconds"],
        exit_code=result["returncode"],
        cwd="/workspace",
    )
    session.name = "evolver"
    session.cwd = "/workspace"
    session.command = spec["command"]
    # Upstream defaults absent price to zero; local Qwen cost is unknown, not free.
    reported_cost = session.cost_usd
    session.cost_usd = None
    session_directory = log_session(session, output / "sessions")
    write_json(
        output / "session-index.json",
        {
            "directory": session_directory,
            "parser": "Meta-Harness@44b9942127847f7421db70d8c7e48407f09a3c70",
            "files_read": session.files_read,
            "files_written": session.files_written,
            "reported_cli_cost_usd_unvalidated": reported_cost,
            "actual_image_requests": "requests/ (Read alone is not proof of transmitted pixels)",
        },
    )
    messages = session.raw_events
    final = next((m for m in reversed(messages) if m.get("type") == "result"), None)
    if not final or final.get("is_error"):
        raise RuntimeError(f"Claude Code did not complete a proposal; inspect {output}")
    write_json(
        output / "usage.json",
        {
            "usage": final.get("usage", {}),
            "model_usage": final.get("modelUsage", {}),
            "seconds": result["seconds"],
            "tool_calls": len(session.tool_calls),
            "local_cost_usd": None,
            "cost_note": "Claude CLI's modelUsage/total_cost_usd are uncalibrated for local Qwen; do not use as billed costs.",
        },
    )
    return result

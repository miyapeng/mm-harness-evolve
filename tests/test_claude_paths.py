from contextlib import contextmanager
from pathlib import Path

import pytest

from mm_harness.runtimes import claude_code


def test_relative_output_is_resolved_before_workspace_chdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    binary = tmp_path / ".venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude"
    binary.parent.mkdir(parents=True)
    binary.touch()
    workspace = Path("runs/example/workspace")
    workspace.mkdir(parents=True)

    @contextmanager
    def gateway(*args):
        yield "http://127.0.0.1:12345"

    class ReachedProcess(Exception):
        pass

    def process(command, *, cwd, directory, timeout):
        assert cwd == workspace.resolve()
        assert Path(command[-1]).is_absolute()
        assert Path(command[-1]).is_file()
        assert directory.is_absolute()
        raise ReachedProcess

    monkeypatch.setattr(claude_code, "messages_gateway", gateway)
    monkeypatch.setattr(claude_code, "run_process", process)
    role = {
        "model": "test",
        "max_tokens": 32,
        "max_turns": 2,
        "wall_timeout_seconds": 60,
        "system_prompt": "test",
    }
    with pytest.raises(ReachedProcess):
        claude_code.run_claude(
            Path("."), workspace, role, "http://example", Path("runs/example/claude")
        )

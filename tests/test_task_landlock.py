"""Exercise inherited filesystem restrictions, including /proc root aliases."""

import subprocess
import sys
from pathlib import Path


def test_landlock_blocks_private_files_and_parent_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "scorer-private"
    secret.write_text("unavailable reference answer")
    code = """
import os, pathlib
from scripts.sandbox_exec import restrict_filesystem
allowed = pathlib.Path(ALLOWED)
secret = pathlib.Path(SECRET)
alias = pathlib.Path('/proc/self/root') / str(secret).lstrip('/')
assert alias.read_text() == secret.read_text()
restrict_filesystem([(pathlib.Path('/usr'), True), (pathlib.Path('/etc'), True),
                     (pathlib.Path('/proc'), True), (allowed, False)])
(allowed/'output').write_text('actor output')
assert (allowed/'output').read_text() == 'actor output'
for path in (secret, alias):
    try:
        path.read_text()
    except PermissionError:
        pass
    else:
        raise AssertionError(f'private data accessible via {path}')
""".replace("ALLOWED", repr(str(allowed))).replace("SECRET", repr(str(secret)))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr

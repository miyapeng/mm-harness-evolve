"""Run under unshare --user --map-root-user --mount --pid --fork.

Mount only runtime dependencies, task inputs/workspace and this attempt's output.
The old datasets, scorer-private files and other runs do not exist inside the root.
"""

import ctypes
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def mount(*args):
    subprocess.run(["mount", *map(str, args)], check=True)


def restrict_filesystem(paths):
    """Linux Landlock ABI >=3; inherited by task children, including browsers.

    Used with an existing proc mount when nested proc creation is denied.
    Landlock also restricts ptrace-like access to processes outside its domain.
    Reference: https://docs.kernel.org/userspace-api/landlock.html
    """
    if platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("Landlock syscall numbers are unverified on this architecture")
    libc = ctypes.CDLL(None, use_errno=True)

    def call(number, *arguments):
        value = libc.syscall(number, *arguments)
        if value < 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
        return value

    abi = call(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError("Task proc compatibility requires Landlock ABI >=3")
    all_access = (1 << 15) - 1
    read_access = (1 << 0) | (1 << 2) | (1 << 3)
    handled = ctypes.c_uint64(all_access)
    ruleset = call(444, ctypes.byref(handled), ctypes.sizeof(handled), 0)

    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    try:
        for path, readonly in paths:
            access = read_access if readonly else all_access
            if not path.is_dir():
                access &= (1 << 0) | (1 << 1) | (1 << 2) | (1 << 14)
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Rule(access, fd)
                call(445, ruleset, 1, ctypes.byref(rule), 0)
            finally:
                os.close(fd)
        if libc.prctl(38, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), "Cannot set no_new_privs")
        call(446, ruleset, 0)
    finally:
        os.close(ruleset)


def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    root = Path(spec["root"])
    root.mkdir(parents=True, exist_ok=True)
    mount("--make-rprivate", "/")
    mount("-t", "tmpfs", "tmpfs", root)
    for source, target, readonly in spec["binds"]:
        src = Path(source)
        dst = root / target.lstrip("/")
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.touch()
        mount("--rbind" if src.is_dir() else "--bind", src, dst)
        if readonly:
            mount("-o", "remount,bind,ro", dst)
    for name in ("tmp", "root", "proc", "dev/pts", "dev/shm"):
        (root / name).mkdir(parents=True, exist_ok=True)
    if spec.get("proc_mode") == "landlock":
        mount("--rbind", "/proc", root / "proc")
        mount("-o", "remount,bind,ro", root / "proc")
        (root / "dev/fd").symlink_to("/proc/self/fd")
    elif spec.get("proc_mode") == "self_only":
        # Some outer containers forbid mounting a new proc filesystem. Expose
        # only this process, which becomes Claude after chroot/exec, plus host
        # resource counters. Never bind the host /proc tree (its pid/root links
        # would expose other processes' filesystems). This mode is for the fixed
        # file-editing B runtime, not a general task execution environment.
        source_proc = Path("/proc") / os.readlink("/proc/self")
        target_proc = root / "proc" / str(os.getpid())
        target_proc.mkdir()
        mount("--bind", source_proc, target_proc)
        mount("-o", "remount,bind,ro", target_proc)
        (root / "proc/self").symlink_to(str(os.getpid()))
        for name in ("meminfo", "cpuinfo", "stat", "uptime", "version", "loadavg"):
            target = root / "proc" / name
            target.touch()
            mount("--bind", Path("/proc") / name, target)
            mount("-o", "remount,bind,ro", target)
        (root / "dev/fd").symlink_to("/proc/self/fd")
    else:
        mount("-t", "proc", "proc", root / "proc", "-o", "nosuid,nodev,noexec")
    mount("-t", "devpts", "devpts", root / "dev/pts", "-o", "newinstance,ptmxmode=0666,mode=0620")
    for source in ("null", "zero", "urandom", "random"):
        target = root / "dev" / source
        target.touch()
        mount("--bind", f"/dev/{source}", target)
    (root / "dev/ptmx").symlink_to("pts/ptmx")
    for target, source in [
        ("bin", "usr/bin"),
        ("sbin", "usr/sbin"),
        ("lib", "usr/lib"),
        ("lib64", "usr/lib64"),
    ]:
        (root / target).symlink_to(source)
    if spec.get("proc_mode") == "landlock":
        restrict_filesystem(
            [(root, True)]
            + [(root / target.lstrip("/"), readonly) for _, target, readonly in spec["binds"]]
            + [(root / "proc", True), (root / "dev", False), (root / "tmp", False)]
        )
    os.chroot(root)
    os.chdir("/workspace")
    os.execvpe(spec["command"][0], spec["command"], spec["env"])


if __name__ == "__main__":
    main()

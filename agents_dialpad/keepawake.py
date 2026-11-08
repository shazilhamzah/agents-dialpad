"""Ask the OS not to idle-sleep while at least one agent reply is running."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


class _Noop:
    def on(self) -> None: ...
    def off(self) -> None: ...


class _Windows:
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001

    def on(self) -> None:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED)

    def off(self) -> None:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)


class _Process:
    """macOS / Linux: keep a helper process alive while awake is needed."""

    def __init__(self, argv: list[str]):
        self.argv = argv
        self.proc: subprocess.Popen | None = None

    def on(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                self.argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def off(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None


def default_backend():
    pid = os.getpid()
    if os.name == "nt":
        return _Windows()
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        return _Process(["caffeinate", "-i", "-w", str(pid)])  # -w: exits by itself if we die
    if shutil.which("systemd-inhibit"):
        # The inner shell loop exits when our process dies, so a crash never leaves the inhibitor behind.
        return _Process([
            "systemd-inhibit",
            "--what=idle:sleep",
            "--who=agents-dialpad",
            "--why=An agent is working",
            "--mode=block",
            "sh",
            "-c",
            f"while kill -0 {pid} 2>/dev/null; do sleep 5; done",
        ])
    return _Noop()


class KeepAwake:
    """Reference counted: on while count > 0."""

    def __init__(self, enabled: bool = True, backend=None):
        self.enabled = enabled
        self.count = 0
        self.backend = backend if backend is not None else (default_backend() if enabled else _Noop())

    def acquire(self) -> None:
        if not self.enabled:
            return
        self.count += 1
        if self.count == 1:
            try:
                self.backend.on()
            except Exception as e:  # never let power management break a reply
                print(f"keep-awake: could not enable ({type(e).__name__}: {e})")

    def release(self) -> None:
        if not self.enabled or self.count == 0:
            return
        self.count -= 1
        if self.count == 0:
            try:
                self.backend.off()
            except Exception as e:
                print(f"keep-awake: could not disable ({type(e).__name__}: {e})")

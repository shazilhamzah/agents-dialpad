"""Subprocess utilities."""
from __future__ import annotations

import os
import signal
import subprocess


def kill_tree(pid: int) -> None:
    """Kill a process and all its children."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

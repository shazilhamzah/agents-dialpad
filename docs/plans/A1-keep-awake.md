# A1. Keep the computer awake while an agent works

- **Size:** S
- **Needs first:** nothing
- **Branch:** `feat/a1-keep-awake`
- **PR title:** `feat: keep the computer awake while an agent is working`

## Goal

While at least one agent reply is running, the computer must not go to sleep because it was idle. When no reply is
running, normal sleep behaviour comes back. This is on by default and can be turned off with `"keep_awake": false`.

## Why

If the laptop sleeps in the middle of a reply, the agent process is frozen and the phone sees nothing until someone
wakes the computer. Users run long tasks from their phone precisely when they are away from the computer.

## Out of scope

- Preventing sleep when the **lid is closed**. That is controlled by OS power settings; we only document it.
- Keeping the screen on. We only stop *system* sleep.

## Read first

- `agents_dialpad/runs.py` (`RunManager.__init__`, `start`, `_drive`)
- `agents_dialpad/app.py` (`create_app`)
- `agents_dialpad/config.py` (`load`)
- `tests/test_integration.py` (the `env` fixture)

## Verify first

1. On Windows, `ctypes.windll.kernel32.SetThreadExecutionState` exists (`python -c "import ctypes; print(ctypes.windll.kernel32.SetThreadExecutionState)"`).
2. Both `RunManager.start()` and the `finally:` block of `RunManager._drive()` run on the asyncio event-loop thread
   (they do today: `start` is called from the async route `send_message`). This matters because on Windows the
   "stay awake" request belongs to the **thread** that made it.

If either is not true, stop and report.

## Steps

### 1. New module `agents_dialpad/keepawake.py`

```python
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
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def off(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None


def default_backend():
    pid = os.getpid()
    if os.name == "nt":
        return _Windows()
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        return _Process(["caffeinate", "-i", "-w", str(pid)])          # -w: exits by itself if we die
    if shutil.which("systemd-inhibit"):
        # The inner shell loop exits when our process dies, so a crash never leaves the inhibitor behind.
        return _Process(["systemd-inhibit", "--what=idle:sleep", "--who=agents-dialpad", "--why=An agent is working",
                         "--mode=block", "sh", "-c", f"while kill -0 {pid} 2>/dev/null; do sleep 5; done"])
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
```

### 2. `config.py`: add the setting

In `load()`, next to the other `setdefault` lines: `cfg.setdefault("keep_awake", True)`.

### 3. `runs.py`: acquire and release

1. `RunManager.__init__` gets a new keyword argument `keep_awake=None` and stores
   `self.keep_awake = keep_awake or KeepAwake(enabled=False)` (import from `.keepawake`).
2. In `start()`, call `self.keep_awake.acquire()` **just before** `asyncio.create_task(...)`.
3. In `_drive()`, call `self.keep_awake.release()` as the **first line of the `finally:` block**, so it runs even when
   the provider raises or the run is stopped.

### 4. `app.py`: wire it

`create_app(cfg=None, token=None, keep_awake=None)`. Inside, after `cfg` is known:

```python
keep_awake = keep_awake or KeepAwake(enabled=bool(cfg.get("keep_awake", True)))
runs = RunManager(..., keep_awake=keep_awake)
```

Expose it for the info endpoint: add `"keep_awake": keep_awake.enabled` to the dict returned by `GET /api/info`.

### 5. `doctor.py`: report it

Add a check after the instructions check: `Check("ok", "Keep awake while working", "on")` or `"off (keep_awake is false)"`
with level `"warn"` when off. On Linux without `systemd-inhibit` and macOS without `caffeinate`, level `"warn"`,
detail `"not supported on this system"`.

## Tests

New file `tests/test_keepawake.py`:

```python
class FakeBackend:
    def __init__(self): self.calls = []
    def on(self): self.calls.append("on")
    def off(self): self.calls.append("off")
```

1. `test_turns_on_once_and_off_after_last_release`: acquire, acquire, release → calls `["on"]`; release → `["on", "off"]`.
2. `test_extra_release_is_harmless`: release with count 0 does nothing and does not go negative.
3. `test_disabled_never_calls_the_backend`.
4. `test_backend_errors_do_not_raise`: backend whose `on()` raises; `acquire()` must not raise.

In `tests/test_integration.py`:

5. Extend the `env` fixture's `make(**extra)` so it accepts `keep_awake=None` and passes it to `create_app`.
6. `test_computer_stays_awake_only_while_a_reply_runs`: pass `KeepAwake(enabled=True, backend=FakeBackend())`; send
   `"SLOW"`; after 1 s assert backend calls == `["on"]`; POST stop; `wait_until_idle`; assert calls == `["on", "off"]`.
7. `test_keep_awake_survives_a_failing_agent`: point `AG_CLAUDE` at a non-existent file (`monkeypatch.setenv("AG_CLAUDE", str(tmp_path / "nope"))`)
   *after* creating the chat; send a message; wait until idle; assert the last call is `"off"`.

## Manual check

1. Run a throwaway copy, start a chat, send a long prompt.
2. While it runs:
   - Windows (admin terminal): `powercfg /requests` lists `python.exe` (or `pythonw.exe`) under `SYSTEM`.
   - macOS: `pmset -g assertions` lists `caffeinate`.
   - Linux: `systemd-inhibit --list` lists `agents-dialpad`.
3. After the reply finishes, the entry is gone.

## Docs

- README: configuration table row `keep_awake` (default `true`); one paragraph under "Start automatically" saying idle
  sleep is blocked while an agent works, and lid-close behaviour is still up to the OS power settings.
- CHANGELOG (Added): "Keeps the computer awake while an agent is working (`keep_awake`)."
- `config.example.json`: `"keep_awake": true`.

## Acceptance checklist

- [ ] With a reply running, the OS reports our process is preventing sleep; after it ends, it does not.
- [ ] Two simultaneous replies: sleep stays blocked until both finish.
- [ ] `"keep_awake": false` disables it; doctor shows "off".
- [ ] A crashing provider still releases the lock (test 7).
- [ ] All tests pass on Windows, macOS and Linux in CI.

## Pitfalls

- On Windows, calling `SetThreadExecutionState` from a worker thread (for example inside `asyncio.to_thread`) does
  nothing useful, because the request dies with that thread. Keep both calls on the event-loop thread.
- Do not use `ES_DISPLAY_REQUIRED`: we do not want the screen kept on.

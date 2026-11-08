"""Codex provider: drives the official `codex` CLI in headless mode.

Normalised events yielded to the UI:
  session      {session_id, model}
  text         {text}                       streamed assistant text
  tool_use     {id, name, input}
  tool_result  {id, text, is_error}
  usage        {info}                       token usage metrics
  done         {is_error, result, cost_usd, duration_ms, denials, stopped}
  error        {message}
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import AsyncIterator

from .. import config
from ._cmd import extra_args

MODES = {
    "readonly": ["-s", "read-only"],
    "edit": ["-s", "workspace-write"],
    "full": ["--dangerously-bypass-approvals-and-sandbox"],
}
MAX_RESULT_CHARS = 4000
REMINDER = "[Keep following the style instructions given at the start of this conversation.]"


def _exe() -> str | None:
    return shutil.which(os.environ.get("AG_CODEX", "codex"))


class _Parser:
    """Turns raw codex JSONL objects into normalised events."""

    def __init__(self, model: str = "") -> None:
        self.model = model
        self.tools_seen: set[str] = set()
        self.notes: list[str] = []
        self.saw_done = False
        self.saw_error = False

    def feed(self, o: dict) -> list[dict]:
        t = o.get("type")
        out: list[dict] = []

        if t == "thread.started":
            out.append({"type": "session", "session_id": o.get("thread_id"), "model": self.model})
        elif t == "item.started":
            item = o.get("item") or {}
            itype = item.get("type")
            iid = item.get("id")
            if itype == "command_execution" and iid:
                if iid not in self.tools_seen:
                    self.tools_seen.add(iid)
                    cmd = item.get("command") or ""
                    out.append({"type": "tool_use", "id": iid, "name": "command_execution", "input": {"command": cmd}})
        elif t == "item.completed":
            item = o.get("item") or {}
            itype = item.get("type")
            iid = item.get("id")
            if itype == "agent_message":
                text = item.get("text")
                if text:
                    out.append({"type": "text", "text": text})
            elif itype == "command_execution" and iid:
                if iid not in self.tools_seen:
                    self.tools_seen.add(iid)
                    cmd = item.get("command") or ""
                    out.append({"type": "tool_use", "id": iid, "name": "command_execution", "input": {"command": cmd}})
                raw_out = item.get("aggregated_output") or ""
                if len(raw_out) > MAX_RESULT_CHARS:
                    raw_out = raw_out[:MAX_RESULT_CHARS] + "\n… (truncated)"
                is_err = item.get("exit_code") != 0 or item.get("status") == "failed"
                out.append({"type": "tool_result", "id": iid, "text": raw_out, "is_error": is_err})
            elif itype == "error":
                self.notes.append(item.get("message") or "")
        elif t == "turn.completed":
            usage = o.get("usage")
            if usage:
                out.append({"type": "usage", "info": usage})
            self.saw_done = True
            out.append({"type": "done", "is_error": False, "result": None, "cost_usd": None, "duration_ms": None, "denials": []})
        elif t == "error":
            self.saw_error = True
            out.append({"type": "error", "message": o.get("message") or ""})
        elif t == "turn.failed":
            err_msg = (o.get("error") or {}).get("message") or "FAILED"
            if not self.saw_error and err_msg:
                out.append({"type": "error", "message": err_msg})
            self.saw_done = True
            out.append({"type": "done", "is_error": True, "result": err_msg, "cost_usd": None, "duration_ms": None, "denials": []})

        return out


class CodexProvider:
    name = "codex"
    label = "Codex"

    def available(self) -> bool:
        return _exe() is not None

    async def models(self) -> list[dict]:
        extra = []
        try:
            extra = config.read_raw().get("codex_models", [])
        except Exception:
            pass
        res = [{"id": "", "label": "Default"}]
        for m in extra:
            if isinstance(m, str) and m:
                res.append({"id": m, "label": m})
            elif isinstance(m, dict) and "id" in m:
                res.append({"id": m["id"], "label": m.get("label", m["id"])})
        return res

    async def stream(
        self, chat: dict, prompt: str, cwd: str, run, instructions: str = "",
        add_dirs=(), approval_timeout: float = 600,
    ) -> AsyncIterator[dict]:
        # add_dirs (uploaded files): not passed on purpose. Codex's `--add-dir` makes a folder *writable*; its sandboxes
        # can already read files outside the workspace, which is all attachments need.
        # approval_timeout: Codex has no "ask before commands" mode yet (supports_ask is not set).
        exe = _exe()
        if not exe:
            raise RuntimeError("`codex` was not found on PATH (set AG_CODEX to its full path).")

        if instructions:
            prefix = instructions if not chat.get("session_id") else REMINDER
            prompt = f"{prefix}\n\n---\nUser message:\n{prompt}"

        mode = chat.get("mode") or "readonly"
        mode_flags = MODES.get(mode, ["-s", "read-only"])
        base_flags = [
            exe, *extra_args("AG_CODEX_ARGS"), "exec",
            "--json", "--skip-git-repo-check",
            "-C", cwd,
            *mode_flags,
        ]
        if chat.get("model"):
            base_flags += ["-m", chat["model"]]

        session_id = chat.get("session_id")
        if session_id:
            args = [*base_flags, "resume", session_id, "-"]
        else:
            args = [*base_flags, "-"]

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 25,
        )
        run.proc = proc
        stderr = bytearray()

        async def drain_stderr() -> None:
            while chunk := await proc.stderr.read(4096):
                if len(stderr) < 8000:
                    stderr.extend(chunk)

        err_task = asyncio.create_task(drain_stderr())
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

            parser = _Parser(model=chat.get("model", ""))
            saw_done = False
            async for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    parser.notes.append(raw.decode("utf-8", "replace"))
                    continue
                if not isinstance(obj, dict):
                    continue
                for ev in parser.feed(obj):
                    saw_done = saw_done or ev["type"] == "done"
                    yield ev

            code = await proc.wait()
            await err_task
            if not saw_done:
                if run.stopped:
                    yield {"type": "done", "is_error": False, "stopped": True}
                else:
                    tail = (" ".join(parser.notes) + " " + stderr.decode("utf-8", "replace")).strip()[-800:]
                    yield {"type": "error", "message": f"codex exited with code {code}. {tail}"}
        finally:
            if proc.returncode is None:
                run.kill()

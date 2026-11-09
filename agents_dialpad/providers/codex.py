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
import re
import shutil
import time
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


_status_cache: tuple[float, dict] | None = None


def codex_error_text(raw: str) -> tuple[str, str | None]:
    """Parse raw error text/JSON from Codex into (message, action)."""
    global _status_cache
    if not raw:
        return "", None

    code = None
    status = None
    err_msg = ""

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            status = data.get("status")
            err_obj = data.get("error")
            if isinstance(err_obj, str):
                try:
                    err_obj = json.loads(err_obj)
                except Exception:
                    pass
            if isinstance(err_obj, dict):
                code = err_obj.get("code") or data.get("code")
                err_msg = err_obj.get("message") or ""
                if not status:
                    status = err_obj.get("status")
            if not err_msg:
                err_msg = data.get("message") or ""
                if isinstance(err_msg, str) and err_msg.startswith("{"):
                    try:
                        inner = json.loads(err_msg)
                        if isinstance(inner, dict):
                            status = status or inner.get("status")
                            inner_err = inner.get("error")
                            if isinstance(inner_err, dict):
                                code = code or inner_err.get("code")
                                err_msg = inner_err.get("message") or err_msg
                    except Exception:
                        pass
    except Exception:
        pass

    full_lower = f"{raw} {err_msg}".lower()

    if code == "model_not_found" or "model is not supported" in full_lower:
        m_match = re.search(r"['`]([A-Za-z0-9._:\-\[\]/]+)['`]\s+model|model\s+['`]([A-Za-z0-9._:\-\[\]/]+)['`]", f"{raw} {err_msg}")
        m_name = (m_match.group(1) or m_match.group(2)) if m_match else ""
        if m_name:
            msg = f"Your Codex account can't use the model '{m_name}'. Pick another model, or set `codex_default_model` in config.json."
        else:
            msg = "Your Codex account can't use this model. Pick another model, or set `codex_default_model` in config.json."
        return msg, "change_model"

    if status == 401 or "not logged in" in full_lower or "unauthorized" in full_lower:
        _status_cache = None
        return "Codex isn't signed in on the computer. Run `codex login` there.", None

    if status == 429 or "usage limit" in full_lower or "rate limit" in full_lower:
        return "Codex usage limit reached. Try again later or use another agent.", None

    if any(k in full_lower for k in ("plan", "subscription", "upgrade")):
        return (
            "Your OpenAI account doesn't include Codex. Use a plan that includes it, "
            "or sign in with an API key (`codex login --with-api-key`)."
        ), None

    return (err_msg if err_msg else raw[:300]), None


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
            usage = o.get("usage") or {}
            if usage:
                out.append({"type": "usage", "info": usage})
            self.saw_done = True
            out.append({
                "type": "done",
                "is_error": False,
                "result": None,
                "cost_usd": None,
                "duration_ms": None,
                "denials": [],
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            })
        elif t == "error":
            self.saw_error = True
            msg_text, action = codex_error_text(o.get("message") or "")
            ev = {"type": "error", "message": msg_text}
            if action:
                ev["action"] = action
            out.append(ev)
        elif t == "turn.failed":
            raw_err = (o.get("error") or {}).get("message") or "FAILED"
            msg_text, action = codex_error_text(raw_err)
            if not self.saw_error and msg_text:
                ev = {"type": "error", "message": msg_text}
                if action:
                    ev["action"] = action
                out.append(ev)
            self.saw_done = True
            done_ev = {
                "type": "done",
                "is_error": True,
                "result": msg_text,
                "cost_usd": None,
                "duration_ms": None,
                "denials": [],
                "input_tokens": None,
                "output_tokens": None,
            }
            if action:
                done_ev["action"] = action
            out.append(done_ev)

        return out


class CodexProvider:
    name = "codex"
    label = "Codex"

    def available(self) -> bool:
        return _exe() is not None

    async def status(self) -> dict:
        global _status_cache
        exe = _exe()
        if not exe:
            return {"state": "not_installed", "note": "not installed"}

        now = time.time()
        if _status_cache and now - _status_cache[0] < 300:
            return _status_cache[1]

        args = [exe, *extra_args("AG_CODEX_ARGS"), "login", "status"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                st = {"state": "unknown", "note": ""}
                _status_cache = (now, st)
                return st

            text = stdout_bytes.decode("utf-8", errors="replace").strip()
            if proc.returncode == 0 and "logged in" in text.lower() and "not logged in" not in text.lower():
                st = {"state": "ready", "note": ""}
            else:
                st = {"state": "not_signed_in", "note": "Codex isn't signed in on the computer"}
        except Exception:
            st = {"state": "unknown", "note": ""}

        _status_cache = (now, st)
        return st

    async def models(self) -> list[dict]:
        extra = []
        default_model = ""
        try:
            raw = config.read_raw()
            extra = raw.get("codex_models", [])
            default_model = raw.get("codex_default_model", "")
        except Exception:
            pass
        default_label = f"Default ({default_model})" if default_model else "Default"
        res = [{"id": "", "label": default_label}]
        seen = {""}
        if default_model:
            seen.add(default_model)
            res.append({"id": default_model, "label": default_model})
        for m in extra:
            if isinstance(m, str) and m and m not in seen:
                seen.add(m)
                res.append({"id": m, "label": m})
            elif isinstance(m, dict) and "id" in m and m["id"] not in seen:
                seen.add(m["id"])
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
        model = chat.get("model")
        if not model:
            try:
                model = config.read_raw().get("codex_default_model", "")
            except Exception:
                model = ""
        if model:
            base_flags += ["-m", model]

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

"""Claude Code provider: drives the official `claude` CLI in headless stream-json mode.

The gateway never touches your login or tokens; the CLI authenticates itself exactly as it
does in your terminal.

Normalised events yielded to the UI:
  session      {session_id, model}
  text         {text}                       streamed assistant text
  tool_use     {id, name, input}
  tool_result  {id, text, is_error}
  usage        {info}                       subscription rate-limit info
  done         {is_error, result, cost_usd, duration_ms, denials, stopped}
  error        {message}
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import AsyncIterator

from ._cmd import extra_args

# UI mode -> `claude --permission-mode`
MODES = {"readonly": "plan", "edit": "acceptEdits", "ask": "default", "full": "bypassPermissions"}
MAX_RESULT_CHARS = 4000


def _exe() -> str | None:
    return shutil.which(os.environ.get("AG_CLAUDE", "claude"))


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class _Parser:
    """Turns raw stream-json objects into normalised events."""

    def __init__(self) -> None:
        self.msg_id: str | None = None
        self.streamed: set[str | None] = set()

    def feed(self, o: dict) -> list[dict]:
        t = o.get("type")
        out: list[dict] = []
        if t == "system":
            if o.get("subtype") == "init":
                out.append({"type": "session", "session_id": o.get("session_id"), "model": o.get("model")})
        elif t == "stream_event":
            if o.get("parent_tool_use_id"):  # sub-agent chatter: skip
                return out
            e = o.get("event") or {}
            et = e.get("type")
            if et == "message_start":
                self.msg_id = (e.get("message") or {}).get("id")
            elif et == "content_block_delta":
                d = e.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    self.streamed.add(self.msg_id)
                    out.append({"type": "text", "text": d["text"]})
        elif t == "assistant":
            if o.get("parent_tool_use_id"):
                return out
            m = o.get("message") or {}
            for b in m.get("content") or []:
                bt = b.get("type")
                if bt == "text" and b.get("text") and m.get("id") not in self.streamed:
                    out.append({"type": "text", "text": b["text"]})
                elif bt == "tool_use":
                    out.append({"type": "tool_use", "id": b.get("id"), "name": b.get("name"), "input": b.get("input")})
        elif t == "user":
            if o.get("parent_tool_use_id"):
                return out
            content = (o.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        text = _result_text(b.get("content"))
                        if len(text) > MAX_RESULT_CHARS:
                            text = text[:MAX_RESULT_CHARS] + "\n… (truncated)"
                        out.append(
                            {"type": "tool_result", "id": b.get("tool_use_id"), "text": text, "is_error": bool(b.get("is_error"))}
                        )
        elif t == "rate_limit_event":
            out.append({"type": "usage", "info": o.get("rate_limit_info")})
        elif t == "control_request":
            req = o.get("request") or {}
            if req.get("subtype") == "can_use_tool":
                out.append(
                    {
                        "type": "approval",
                        "id": o.get("request_id"),
                        "tool": req.get("tool_name"),
                        "input": req.get("input"),
                    }
                )
        elif t == "result":
            denials = [d.get("tool_name") if isinstance(d, dict) else str(d) for d in o.get("permission_denials") or []]
            out.append(
                {
                    "type": "done",
                    "is_error": bool(o.get("is_error")),
                    "result": o.get("result"),
                    "cost_usd": o.get("total_cost_usd"),
                    "duration_ms": o.get("duration_ms"),
                    "denials": denials,
                }
            )
        return out


class ClaudeProvider:
    name = "claude"
    label = "Claude Code"
    supports_ask = True

    MODELS = [
        {"id": "", "label": "Default"},
        {"id": "claude-fable-5-1", "label": "Fable 5.1"},
        {"id": "claude-opus-5-5", "label": "Opus 5.5"},
        {"id": "claude-sonnet-5-5", "label": "Sonnet 5.5"},
        {"id": "claude-haiku-5-5", "label": "Haiku 5.5"},
    ]

    def available(self) -> bool:
        return _exe() is not None

    async def models(self) -> list[dict]:
        return self.MODELS

    async def stream(
        self,
        chat: dict,
        prompt: str,
        cwd: str,
        run,
        instructions: str = "",
        add_dirs: tuple[str, ...] | list[str] = (),
        approval_timeout: float = 600.0,
    ) -> AsyncIterator[dict]:
        exe = _exe()
        if not exe:
            raise RuntimeError("`claude` was not found on PATH (set AG_CLAUDE to its full path).")
        env_timeout = os.environ.get("AG_APPROVAL_TIMEOUT")
        timeout = float(env_timeout) if env_timeout else approval_timeout
        is_ask = chat.get("mode") == "ask"
        args = [
            exe, *extra_args("AG_CLAUDE_ARGS"), "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-mode", MODES.get(chat.get("mode"), "plan"),
        ]
        if is_ask:
            args += ["--input-format", "stream-json", "--permission-prompts", "host", "--permission-prompt-tool", "stdio"]
        for d in add_dirs:
            args += ["--add-dir", d]
        if chat.get("model"):
            args += ["--model", chat["model"]]
        if instructions:
            args += ["--append-system-prompt", instructions]
        if chat.get("session_id"):
            args += ["--resume", chat["session_id"]]

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 25,  # stream-json lines can be very long
        )
        run.proc = proc
        stderr = bytearray()

        async def drain_stderr() -> None:
            while chunk := await proc.stderr.read(4096):
                if len(stderr) < 8000:
                    stderr.extend(chunk)

        err_task = asyncio.create_task(drain_stderr())
        try:
            if is_ask:
                user_msg = {"type": "user", "message": {"role": "user", "content": prompt}}
                proc.stdin.write((json.dumps(user_msg) + "\n").encode("utf-8"))
                await proc.stdin.drain()
            else:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            parser = _Parser()
            saw_done = False
            async for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                for ev in parser.feed(obj):
                    if ev["type"] == "approval":
                        req_id = ev["id"]
                        yield ev
                        allow, by = await run.wait_decision(req_id, timeout)
                        if allow:
                            resp = {
                                "type": "control_response",
                                "response": {
                                    "subtype": "success",
                                    "request_id": req_id,
                                    "response": {
                                        "behavior": "allow",
                                        "updatedInput": ev.get("input"),
                                    },
                                },
                            }
                        else:
                            resp = {
                                "type": "control_response",
                                "response": {
                                    "subtype": "success",
                                    "request_id": req_id,
                                    "response": {
                                        "behavior": "deny",
                                        "message": "The user denied this",
                                    },
                                },
                            }
                        if proc.stdin and not proc.stdin.is_closing():
                            try:
                                proc.stdin.write((json.dumps(resp) + "\n").encode("utf-8"))
                                await proc.stdin.drain()
                            except (OSError, RuntimeError):
                                pass
                        yield {"type": "approval_result", "id": req_id, "allow": allow, "by": by}
                        continue

                    saw_done = saw_done or ev["type"] == "done"
                    if ev["type"] == "done" and proc.stdin and not proc.stdin.is_closing():
                        try:
                            proc.stdin.close()
                        except (OSError, RuntimeError):
                            pass
                    yield ev

            code = await proc.wait()
            await err_task
            if not saw_done:
                if run.stopped:
                    yield {"type": "done", "is_error": False, "stopped": True}
                else:
                    tail = stderr.decode("utf-8", "replace").strip()[-800:]
                    yield {"type": "error", "message": f"claude exited with code {code}. {tail}"}
        finally:
            if proc.returncode is None:
                run.kill()

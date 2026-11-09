"""Antigravity provider: drives the official `agy` CLI in headless stream-json mode.

Differences from Claude Code that this adapter hides:
  * the prompt is passed as `-p=<prompt>` (there is no stdin prompt),
  * there is no system-prompt flag, so instructions are prefixed to the user's message,
  * a conversation is resumed with `--conversation <id>`,
  * stream events are `{"event": "init" | "step_update" | "result", ...}`.

Emits the same normalised events as ClaudeProvider.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from typing import AsyncIterator

from ._cmd import extra_args
from ..approvals import approval_event

MODES = {"readonly": "plan", "edit": "accept-edits", "ask": "default", "full": "accept-edits"}  # "full" also adds --dangerously-skip-permissions
MAX_PROMPT_CHARS = 28_000  # Windows command-line limit is ~32k
REMINDER = "[Keep following the style instructions given at the start of this conversation.]"

_models_cache: tuple[float, list[dict]] | None = None
_limits_cache: tuple[float, dict] | None = None


def _exe() -> str | None:
    return shutil.which(os.environ.get("AG_AGY", "agy"))


class _Parser:
    def __init__(self) -> None:
        self.tools_seen: set[int] = set()
        self.streamed_text = False
        self.notes: list[str] = []  # non-JSON lines the CLI printed (e.g. permission hints)

    def feed(self, o: dict) -> list[dict]:
        out: list[dict] = []
        ev = o.get("event")
        if ev == "init":
            out.append({"type": "session", "session_id": o.get("conversation_id"), "model": (o.get("init") or {}).get("model")})
        elif ev == "step_update":
            su = o.get("step_update") or {}
            kind, state = su.get("step_type"), su.get("state")
            if kind == "agent_response" and su.get("text_delta"):
                self.streamed_text = True
                out.append({"type": "text", "text": su["text_delta"]})
            elif kind == "tool":
                sid = su.get("step_index")
                if sid not in self.tools_seen:
                    self.tools_seen.add(sid)
                    params = (su.get("tool_info") or {}).get("parameters") or {}
                    out.append({"type": "tool_use", "id": str(sid), "name": su.get("tool_name"), "input": params})
                if state not in ("ACTIVE", None):
                    out.append({"type": "tool_result", "id": str(sid), "text": "", "is_error": state != "DONE"})
        elif ev == "result":
            r = o.get("result") or {}
            ok = r.get("status") == "SUCCESS"
            if ok and r.get("response") and not self.streamed_text:
                out.append({"type": "text", "text": r["response"]})
            denials = [d.get("display_name") or d.get("action") for d in r.get("denied_actions") or [] if isinstance(d, dict)]
            if ok and not r.get("response") and not self.streamed_text and self.notes:
                out.append({"type": "error", "message": " ".join(self.notes)[:800]})
            secs = r.get("duration_seconds")
            usage = r.get("usage") or {}
            out.append(
                {
                    "type": "done",
                    "is_error": not ok,
                    "result": None if ok else (r.get("status") or "FAILED"),
                    "cost_usd": None,
                    "duration_ms": int(secs * 1000) if secs else None,
                    "denials": denials,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            )
        return out


class AntigravityProvider:
    name = "antigravity"
    label = "Antigravity"
    supports_ask = True

    def available(self) -> bool:
        return _exe() is not None

    async def models(self) -> list[dict]:
        """`agy models` prints `<id>\\t<label>` per line; cached for 10 minutes."""
        global _models_cache
        if _models_cache and time.time() - _models_cache[0] < 600:
            return _models_cache[1]
        exe = _exe()
        found: list[dict] = []
        if exe:
            try:
                proc = await asyncio.create_subprocess_exec(
                    exe, *extra_args("AG_AGY_ARGS"), "models",
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), 30)
                for line in stdout.decode("utf-8", "replace").splitlines():
                    if "\t" in line:
                        mid, label = line.split("\t", 1)
                        found.append({"id": mid.strip(), "label": label.strip()})
            except (asyncio.TimeoutError, OSError):
                pass
        result = ([{"id": "", "label": "Default"}] + found) if found else [{"id": "", "label": "Default"}]
        _models_cache = (time.time(), result)
        return result

    async def limits(self, force: bool = False) -> dict:
        """Quota from `agy -p=/usage` (no model call). Rows: group, label, % remaining, reset time. Cached 60s."""
        global _limits_cache
        if not force and _limits_cache and time.time() - _limits_cache[0] < 60:
            return _limits_cache[1]
        exe, rows, note = _exe(), [], None
        if not exe:
            note = "`agy` was not found on PATH."
        else:
            try:
                proc = await asyncio.create_subprocess_exec(
                    exe, *extra_args("AG_AGY_ARGS"), "--output-format", "text", "-p=/usage",
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), 40)
                except asyncio.TimeoutError:
                    proc.kill()
                    raise
                text = stdout.decode("utf-8", "replace")
                for line in text.splitlines():
                    parts = [p.strip() for p in line.split("\t")]
                    if len(parts) >= 4 and parts[2].endswith("%") and parts[2][:-1].isdigit():
                        group, label = parts[0], parts[1]
                        label = label.replace(" Remaining", "").replace(" Limit", "").strip()
                        if label.startswith(group):
                            label = label[len(group):].strip() or label
                        rows.append({"group": group, "label": label, "remaining": int(parts[2][:-1]), "resets_at": parts[3]})
                if not rows:
                    note = (text.strip().splitlines() or ["No limits data returned."])[0][:200]
            except (asyncio.TimeoutError, OSError):
                note = "Timed out reading limits."
        result = {"rows": rows, "note": note, "fetched": time.time()}
        if rows:  # don't cache failures
            _limits_cache = (time.time(), result)
        return result

    async def stream(
        self,
        chat: dict,
        prompt: str,
        cwd: str,
        run,
        instructions: str = "",
        add_dirs: tuple[str, ...] | list[str] = (),
        approval_timeout: float = 600,
        **kwargs,
    ) -> AsyncIterator[dict]:
        if chat.get("mode") == "ask":
            async for ev in self._stream_acp(
                chat, prompt, cwd, run, instructions=instructions, add_dirs=add_dirs, approval_timeout=approval_timeout
            ):
                yield ev
            return

        exe = _exe()
        if not exe:
            raise RuntimeError("`agy` was not found on PATH (set AG_AGY to its full path).")
        if instructions:
            prefix = instructions if not chat.get("session_id") else REMINDER
            prompt = f"{prefix}\n\n---\nUser message:\n{prompt}"
        if len(prompt) > MAX_PROMPT_CHARS:
            raise RuntimeError(f"Message too long for Antigravity ({len(prompt)} chars; limit {MAX_PROMPT_CHARS}).")

        args = [exe, *extra_args("AG_AGY_ARGS"), "--output-format", "stream-json", "--mode", MODES.get(chat.get("mode"), "plan")]
        for d in add_dirs:
            args += ["--add-dir", d]
        if chat.get("mode") == "full":
            args.append("--dangerously-skip-permissions")  # headless cannot prompt; the CLI still blocks its system denylist
        if chat.get("model"):
            args += ["--model", chat["model"]]
        if chat.get("session_id"):
            args += ["--conversation", chat["session_id"]]
        args.append("-p=" + prompt)

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
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
            parser = _Parser()
            saw_done = False
            async for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
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
                    yield {"type": "error", "message": f"agy exited with code {code}. {tail}"}
        finally:
            if proc.returncode is None:
                run.kill()

    async def _stream_acp(
        self,
        chat: dict,
        prompt: str,
        cwd: str,
        run,
        instructions: str = "",
        add_dirs: tuple[str, ...] | list[str] = (),
        approval_timeout: float = 600,
    ) -> AsyncIterator[dict]:
        exe = _exe()
        if not exe:
            raise RuntimeError("`agy` was not found on PATH (set AG_AGY to its full path).")
        env_timeout = os.environ.get("AG_APPROVAL_TIMEOUT")
        timeout = float(env_timeout) if env_timeout else approval_timeout
        if instructions:
            prefix = instructions if not chat.get("session_id") else REMINDER
            prompt = f"{prefix}\n\n---\nUser message:\n{prompt}"

        args = [exe, *extra_args("AG_AGY_ARGS"), "acp"]
        for d in add_dirs:
            args += ["--add-dir", d]

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

        rpc_id = 1

        async def send_rpc(msg: dict) -> None:
            if proc.stdin and not proc.stdin.is_closing():
                payload = (json.dumps(msg) + "\n").encode("utf-8")
                proc.stdin.write(payload)
                await proc.stdin.drain()

        init_id = rpc_id
        rpc_id += 1
        await send_rpc({
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "capabilities": {},
                "clientInfo": {"name": "agents-dialpad", "version": "0.1.0"},
            },
        })

        session_rpc_id = rpc_id
        rpc_id += 1
        sess_id = chat.get("session_id")
        if sess_id:
            await send_rpc({
                "jsonrpc": "2.0",
                "id": session_rpc_id,
                "method": "session/load",
                "params": {"sessionId": sess_id, "cwd": str(cwd).replace("\\", "/"), "mcpServers": []},
            })
        else:
            await send_rpc({
                "jsonrpc": "2.0",
                "id": session_rpc_id,
                "method": "session/new",
                "params": {"cwd": str(cwd).replace("\\", "/"), "mcpServers": []},
            })

        saw_done = False
        prompt_sent = False
        prompt_rpc_id: int | None = None

        try:
            async for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue

                if obj.get("id") == session_rpc_id and "result" in obj:
                    res = obj["result"]
                    active_sess = res.get("sessionId")
                    if active_sess:
                        chat["session_id"] = active_sess
                        yield {
                            "type": "session",
                            "session_id": active_sess,
                            "model": chat.get("model") or (res.get("models") or {}).get("currentModelId"),
                        }

                    if chat.get("model"):
                        model_id = rpc_id
                        rpc_id += 1
                        await send_rpc({
                            "jsonrpc": "2.0",
                            "id": model_id,
                            "method": "session/set_config_option",
                            "params": {
                                "sessionId": active_sess,
                                "configId": "model",
                                "value": chat["model"],
                            },
                        })

                    prompt_rpc_id = rpc_id
                    rpc_id += 1
                    prompt_sent = True
                    await send_rpc({
                        "jsonrpc": "2.0",
                        "id": prompt_rpc_id,
                        "method": "session/prompt",
                        "params": {
                            "sessionId": active_sess,
                            "prompt": [{"type": "text", "text": prompt}],
                        },
                    })
                    continue

                if not prompt_sent:
                    continue

                if obj.get("method") == "session/update":
                    update = (obj.get("params") or {}).get("update") or {}
                    u_type = update.get("sessionUpdate")
                    if u_type == "agent_message_chunk":
                        text = ((update.get("content") or {}).get("text")) or ""
                        if text:
                            yield {"type": "text", "text": text}
                    elif u_type == "tool_call":
                        tool_name = update.get("name")
                        t_id = update.get("toolCallId")
                        params = update.get("rawInput") or update.get("args") or {}
                        yield {"type": "tool_use", "id": str(t_id), "name": tool_name, "input": params}
                    elif u_type == "tool_call_update":
                        status = update.get("status")
                        t_id = update.get("toolCallId")
                        if status in ("completed", "failed"):
                            out_text = ((update.get("rawOutput") or {}).get("output")) or ""
                            yield {
                                "type": "tool_result",
                                "id": str(t_id),
                                "text": out_text,
                                "is_error": status == "failed",
                            }
                    continue

                if obj.get("method") == "session/request_permission":
                    req_id = str(obj.get("id"))
                    params = obj.get("params") or {}
                    tool_call = params.get("toolCall") or {}
                    tool_name = tool_call.get("name", "unknown")
                    args_data = tool_call.get("rawInput") or tool_call.get("args") or {}
                    desc = args_data.get("toolSummary", "") if isinstance(args_data, dict) else tool_call.get("title", "")
                    if not desc:
                        desc = tool_call.get("title", "")
                    yield approval_event(
                        req_id=req_id,
                        tool=tool_name,
                        raw_input=args_data,
                        description=desc,
                    )
                    allow, by = await run.wait_decision(req_id, timeout)
                    option_id = "allow" if allow else "deny"
                    resp = {
                        "jsonrpc": "2.0",
                        "id": obj.get("id"),
                        "result": {
                            "outcome": {
                                "outcome": "selected",
                                "optionId": option_id,
                            }
                        },
                    }
                    await send_rpc(resp)
                    yield {
                        "type": "approval_result",
                        "id": req_id,
                        "allow": allow,
                        "by": by,
                    }
                    continue

                if prompt_rpc_id is not None and obj.get("id") == prompt_rpc_id:
                    saw_done = True
                    if proc.stdin and not proc.stdin.is_closing():
                        try:
                            proc.stdin.close()
                        except (OSError, RuntimeError):
                            pass
                    yield {"type": "done", "is_error": False, "stopped": run.stopped}
                    break

            await err_task
            if not saw_done:
                if run.stopped:
                    yield {"type": "done", "is_error": False, "stopped": True}
                else:
                    code = await proc.wait()
                    err_msg = stderr.decode("utf-8", "replace").strip()[-800:]
                    yield {"type": "error", "message": f"agy acp exited with code {code}. {err_msg}"}
        finally:
            if proc.returncode is None:
                run.kill()

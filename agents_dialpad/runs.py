"""Background runs.

A turn runs as a background task that records its events, so the phone can lock, lose signal,
and reconnect later and still see (or replay) everything the agent did.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
import uuid

from .keepawake import KeepAwake
from .proc import kill_tree
from .providers import PROVIDERS
from pathlib import Path
from . import uploads
from .store import Store


class Run:
    def __init__(self, chat_id: str, project: str = ""):
        self.project = project
        self.id = uuid.uuid4().hex
        self.chat_id = chat_id
        self.events: list[dict] = []
        self.done = False
        self.stopped = False
        self.proc: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task | None = None
        self.cond = asyncio.Condition()

    async def emit(self, ev: dict) -> None:
        async with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.done = True
            self.cond.notify_all()

    def kill(self) -> None:
        proc = self.proc
        if not proc or proc.returncode is not None:
            return
        kill_tree(proc.pid)


def _compact(events: list[dict]) -> list[dict]:
    """Merge consecutive text deltas so saved chats stay small."""
    out: list[dict] = []
    for ev in events:
        if ev["type"] in ("ping",):
            continue
        if ev["type"] == "text" and out and out[-1]["type"] == "text":
            out[-1] = {"type": "text", "text": out[-1]["text"] + ev["text"]}
        else:
            out.append(ev)
    return out


class RunManager:
    def __init__(
        self,
        store: Store,
        projects: dict[str, str],
        get_instructions=lambda: "",
        allow_full=lambda: False,
        keep_awake: KeepAwake | None = None,
        on_finish=None,
    ):
        self.store = store
        self.projects = projects
        self.get_instructions = get_instructions
        self.allow_full = allow_full
        self.keep_awake = keep_awake or KeepAwake(enabled=False)
        self.on_finish = on_finish
        self.runs: dict[str, Run] = {}  # latest run per chat
        self.usage_path = store.dir.parent / "usage.json"  # last subscription usage, survives restarts
        self.usage: dict | None = None
        try:
            self.usage = json.loads(self.usage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def active(self, chat_id: str) -> Run | None:
        run = self.runs.get(chat_id)
        return run if run and not run.done else None

    def active_in_project(self, project: str) -> bool:
        return any(r.project == project for r in self.runs.values() if not r.done)

    def start(self, chat: dict, text: str, attachments: list[Path] = ()) -> Run:
        run = Run(chat["id"], project=chat.get("project", ""))
        self.runs[chat["id"]] = run
        user_msg = {"role": "user", "text": text, "ts": time.time()}
        if attachments:
            user_msg["attachments"] = [p.name for p in attachments]
        chat["messages"].append(user_msg)
        if chat["title"] == "New chat":
            chat["title"] = " ".join(text.split())[:48] or "New chat"
        chat["updated"] = time.time()
        self.store.save(chat)
        self.keep_awake.acquire()
        prompt_text = text
        if attachments:
            prompt_text = (
                text
                + "\n\nAttached files (read them from these paths):\n"
                + "\n".join(f"- {p}" for p in attachments)
            )
        udir = uploads.upload_dir(chat["id"])
        add_dirs = [str(udir)] if (attachments or udir.exists()) else []
        run.task = asyncio.create_task(self._drive(chat, run, prompt_text, add_dirs=add_dirs))
        return run

    async def _drive(self, chat: dict, run: Run, text: str, add_dirs: list[str] = ()) -> None:
        provider = PROVIDERS[chat["provider"]]
        cwd = self.projects[chat["project"]]
        try:
            # If full access was switched off in config.json, old "full" chats quietly drop to "can edit".
            effective = chat if (chat.get("mode") != "full" or self.allow_full()) else {**chat, "mode": "edit"}
            async for ev in provider.stream(effective, text, cwd, run, self.get_instructions(), add_dirs=add_dirs):
                if ev["type"] == "session" and ev.get("session_id"):
                    chat["session_id"] = ev["session_id"]
                if ev["type"] == "usage" and ev.get("info"):
                    self.usage = ev["info"]
                    try:
                        self.usage_path.write_text(json.dumps(self.usage), encoding="utf-8")
                    except OSError:
                        pass
                await run.emit(ev)
        except Exception as e:  # noqa: BLE001 - surface everything to the phone
            await run.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            self.keep_awake.release()
            try:
                fresh = self.store.get(chat["id"])
            except KeyError:
                fresh = None  # deleted while the reply was running: do not bring it back
            if fresh is not None:
                fresh["messages"].append(
                    {"role": "assistant", "run_id": run.id, "events": _compact(run.events), "ts": time.time()}
                )
                if chat.get("session_id"):
                    fresh["session_id"] = chat["session_id"]
                fresh["updated"] = time.time()
                self.store.save(fresh)
            await run.finish()  # after persisting, so readers never miss the saved message
            if self.on_finish and not run.stopped:
                try:
                    await self.on_finish(chat["id"], run)
                except Exception as e:
                    print(f"on_finish failed: {type(e).__name__}: {e}")

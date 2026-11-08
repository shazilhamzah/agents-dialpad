"""HTTP API + static PWA. `create_app()` builds a fresh, independent app (the tests rely on that)."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pathlib import Path
from . import config, export, gitview, pairing, push, quick
from .keepawake import KeepAwake
from .providers import PLANNED, PROVIDERS
from .runs import RunManager
from .store import Store

MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-\[\]/]{0,100}")  # never starts with '-': it is passed as an argument

BASE_MODES = [
    {"id": "readonly", "label": "Read-only (plan)"},
    {"id": "edit", "label": "Can edit files"},
]
FULL_MODE = {"id": "full", "label": "Full access (runs commands, no prompts)"}


class NewChat(BaseModel):
    provider: str
    project: str
    mode: str = "readonly"
    model: str = ""


class ChatPatch(BaseModel):
    model: str | None = None
    title: str | None = Field(default=None, max_length=80)
    pinned: bool | None = None


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class PushSubscribe(BaseModel):
    subscription: dict
    label: str = "device"


class PushUnsubscribe(BaseModel):
    endpoint: str


class RevertPath(BaseModel):
    path: str


def create_app(cfg: dict | None = None, token: str | None = None, keep_awake: KeepAwake | None = None) -> FastAPI:
    if cfg is None or token is None:
        cfg, token = config.load()
    keep_awake = keep_awake or KeepAwake(enabled=bool(cfg.get("keep_awake", True)))
    store = Store(config.DATA / "chats")
    subs = push.Subscriptions(config.DATA / "push.json")

    async def notify(chat_id: str, run):
        if not subs.all():
            return
        try:
            chat = store.get(chat_id)
        except KeyError:
            return
        done = next((e for e in reversed(run.events) if e["type"] == "done"), None)
        payload = push.build_payload(chat, done, bool(cfg.get("push_show_titles")))
        await asyncio.to_thread(push.send_all, subs, payload, config.DATA, cfg["push_contact"])

    runs = RunManager(
        store,
        cfg["projects"],
        lambda: config.read_instructions(cfg),
        lambda: bool(cfg.get("allow_full_access")),
        keep_awake=keep_awake,
        on_finish=notify,
    )

    def modes() -> list[dict]:
        """'Full access' only exists when `"allow_full_access": true` is set in config.json."""
        return BASE_MODES + ([FULL_MODE] if cfg.get("allow_full_access") else [])

    def require_token(authorization: str | None = Header(default=None)) -> None:
        supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not secrets.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "Invalid or missing token")

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    async def check_model(provider, model: str) -> None:
        if model == "":
            return
        if not MODEL_RE.fullmatch(model):
            raise HTTPException(400, "Invalid model name")
        known = {m["id"] for m in await provider.models()}
        if len(known) > 1 and model not in known:  # only enforce when the CLI gave us a real list
            raise HTTPException(400, f"Unknown model '{model}' for {provider.label}")

    def chat_or_404(chat_id: str) -> dict:
        try:
            return store.get(chat_id)
        except KeyError:
            raise HTTPException(404, "No such chat") from None

    @api.get("/info")
    async def info():
        providers = [
            {"name": p.name, "label": p.label, "available": p.available(), "models": await p.models() if p.available() else []}
            for p in PROVIDERS.values()
        ]
        return {
            "providers": providers + [{**p, "available": False, "models": []} for p in PLANNED],
            "projects": list(cfg["projects"]),
            "modes": modes(),
            "usage": runs.usage,
            "keep_awake": keep_awake.enabled,
        }

    @api.get("/pair")
    def pair():
        base = pairing.tailscale_url(cfg["port"])
        link = pairing.pair_link(base or f"http://127.0.0.1:{cfg['port']}/", token)
        return {"url": link, "remote": base is not None, "qr": pairing.qr_svg_data_uri(link)}

    @api.get("/push/key")
    def push_key():
        try:
            return {"publicKey": push.vapid_public_key(config.DATA)}
        except push.PushUnavailable as e:
            raise HTTPException(501, f"Notifications need the push extra: {e}")

    @api.post("/push/subscribe")
    def push_subscribe(body: PushSubscribe):
        try:
            subs.add(body.subscription, body.label)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @api.post("/push/unsubscribe")
    def push_unsubscribe(body: PushUnsubscribe):
        subs.remove(body.endpoint)
        return {"ok": True}

    @api.post("/push/test")
    async def push_test():
        payload = {"title": "agents-dialpad", "body": "Notifications are working", "tag": "test", "url": "/"}
        try:
            sent = await asyncio.to_thread(push.send_all, subs, payload, config.DATA, cfg["push_contact"])
            return {"sent": sent}
        except push.PushUnavailable as e:
            raise HTTPException(501, str(e))

    def claude_limits() -> dict:
        """Claude Code reports its subscription windows on every turn; we keep the latest."""
        u = runs.usage
        rows, expired = [], False
        now = datetime.now(timezone.utc).timestamp()
        if u:
            for key, label in (("five_hour", "5-hour"), ("seven_day", "Weekly")):
                w = (u.get("unifiedWindows") or {}).get(key)
                if w and w.get("utilization") is not None:
                    resets = w.get("resetsAt")
                    if resets and resets < now:  # that window has reset since the last message: the number is stale
                        expired = True
                        continue
                    used = w["utilization"] * 100 if w["utilization"] <= 1 else w["utilization"]
                    rows.append({
                        "group": "Claude Code", "label": label, "remaining": max(0, round(100 - used)),
                        "resets_at": datetime.fromtimestamp(resets, timezone.utc).isoformat() if resets else None,
                    })
        note = None
        if not rows:
            note = ("The windows from your last Claude Code message have reset. Send one to refresh." if expired
                    else "Appears after your first Claude Code message.")
        return {"rows": rows, "note": note, "fetched": None}

    @api.get("/limits")
    async def limits(refresh: bool = False):
        out = []
        for p in PROVIDERS.values():
            if not p.available():
                continue
            if p.name == "claude":
                data = claude_limits()
            elif hasattr(p, "limits"):
                data = await p.limits(refresh)
            else:
                continue
            out.append({"name": p.name, "label": p.label, **data})
        return {"providers": out}

    @api.get("/chats")
    def list_chats(q: str = Query(default="", max_length=100)):
        chats = store.search(q) if q else store.list()
        for c in chats:
            c["running"] = runs.active(c["id"]) is not None
        return {"chats": chats, "usage": runs.usage}

    @api.post("/chats")
    async def create_chat(body: NewChat):
        prov = PROVIDERS.get(body.provider)
        if not prov or not prov.available():
            raise HTTPException(400, f"Provider '{body.provider}' is not available")
        if body.project not in cfg["projects"]:
            raise HTTPException(400, "Unknown project")
        if body.mode not in {m["id"] for m in modes()}:
            raise HTTPException(400, "Unknown mode")
        await check_model(prov, body.model)
        return store.create(body.provider, body.project, body.mode, body.model)

    quick_locks: dict[str, asyncio.Lock] = {}

    @api.get("/projects/{project}/commands")
    def list_commands(project: str):
        if project not in cfg["projects"]:
            raise HTTPException(404, "Unknown project")
        cmds = quick.commands_for(cfg.get("quick_commands", {}), project)
        return [{"index": c["index"], "label": c["label"]} for c in cmds]

    @api.post("/projects/{project}/commands/{index}")
    async def run_command_endpoint(project: str, index: int):
        if project not in cfg["projects"]:
            raise HTTPException(404, "Unknown project")
        cmds = quick.commands_for(cfg.get("quick_commands", {}), project)
        cmd = next((c for c in cmds if c["index"] == index), None)
        if cmd is None:
            raise HTTPException(404, "Unknown command")
        lock = quick_locks.setdefault(project, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Another quick command is still running in this project")
        async with lock:
            cwd = cfg["projects"][project]
            try:
                return await quick.run(cmd["run"], cwd, cmd["timeout"])
            except FileNotFoundError as e:
                raise HTTPException(400, f"'{e}' was not found on this computer's PATH")

    @api.get("/projects/{project}/changes")
    async def get_project_changes(project: str):
        if project not in cfg["projects"]:
            raise HTTPException(404, "Unknown project")
        root = Path(cfg["projects"][project])
        try:
            return await gitview.status(root)
        except FileNotFoundError:
            raise HTTPException(501, "git is not installed on this computer")
        except TimeoutError:
            raise HTTPException(504, "git took too long")

    @api.get("/projects/{project}/changes/diff")
    async def get_project_diff(project: str, path: str = Query(...)):
        if project not in cfg["projects"]:
            raise HTTPException(404, "Unknown project")
        root = Path(cfg["projects"][project])
        try:
            return await gitview.diff(root, path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(501, "git is not installed on this computer")
        except TimeoutError:
            raise HTTPException(504, "git took too long")

    @api.post("/projects/{project}/changes/revert")
    async def revert_project_file(project: str, body: RevertPath):
        if project not in cfg["projects"]:
            raise HTTPException(404, "Unknown project")
        if runs.active_in_project(project):
            raise HTTPException(409, "An agent is working in this project; wait for it to finish")
        root = Path(cfg["projects"][project])
        try:
            await gitview.revert(root, body.path)
            return {"ok": True}
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(409, str(e))
        except FileNotFoundError:
            raise HTTPException(501, "git is not installed on this computer")
        except TimeoutError:
            raise HTTPException(504, "git took too long")

    @api.patch("/chats/{chat_id}")
    async def patch_chat(chat_id: str, body: ChatPatch):
        """Change the model, title or pin state."""
        chat = chat_or_404(chat_id)
        if body.model is not None:
            if runs.active(chat_id):
                raise HTTPException(409, "Wait for the current reply to finish before changing the model")
            await check_model(PROVIDERS[chat["provider"]], body.model)
            chat["model"] = body.model
        if body.title is not None:
            t = " ".join(body.title.split())
            if not t:
                raise HTTPException(400, "Title can't be empty")
            chat["title"] = t
        if body.pinned is not None:
            chat["pinned"] = body.pinned
        store.save(chat)
        out = {"model": chat.get("model", "")}
        if body.title is not None or body.pinned is not None:
            out["title"] = chat.get("title", "")
            out["pinned"] = bool(chat.get("pinned", False))
        return out

    @api.get("/chats/{chat_id}/export")
    def export_chat(chat_id: str):
        chat = chat_or_404(chat_id)
        prov = PROVIDERS.get(chat["provider"])
        label = prov.label if prov else chat["provider"]
        md = export.chat_to_markdown(chat, label)
        fname = export.filename_for(chat)
        return Response(
            content=md,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @api.get("/chats/{chat_id}")
    def get_chat(chat_id: str):
        chat = chat_or_404(chat_id)
        run = runs.active(chat_id)
        if run and chat["messages"] and chat["messages"][-1].get("run_id") == run.id:
            chat["messages"].pop()  # already saved but still streaming: the client replays it live
        chat["running"] = run is not None
        return chat

    @api.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        chat_or_404(chat_id)
        run = runs.active(chat_id)
        if run:
            run.stopped = True
            run.kill()
        store.delete(chat_id)
        return {"ok": True}

    @api.post("/chats/{chat_id}/messages", status_code=202)
    async def send_message(chat_id: str, body: NewMessage):  # async: must run on the event loop
        chat = chat_or_404(chat_id)
        if runs.active(chat_id):
            raise HTTPException(409, "This chat is already running")
        run = runs.start(chat, body.text)
        return {"run_id": run.id}

    @api.post("/chats/{chat_id}/stop")
    async def stop(chat_id: str):
        run = runs.active(chat_id)
        if run:
            run.stopped = True
            run.kill()
        return {"ok": True}

    @api.get("/chats/{chat_id}/stream")
    async def stream(chat_id: str, start: int = 0):
        """NDJSON stream of the latest run's events, from index `start`. Safe to reconnect."""
        chat_or_404(chat_id)
        run = runs.runs.get(chat_id)

        async def gen():
            if run is None:
                return
            i = max(0, start)
            while True:
                async with run.cond:
                    if i >= len(run.events) and not run.done:
                        try:
                            await asyncio.wait_for(run.cond.wait(), 15)
                        except asyncio.TimeoutError:
                            pass
                    batch = run.events[i:]
                    done = run.done
                if batch:
                    i += len(batch)
                    yield "".join(json.dumps(e) + "\n" for e in batch)
                elif not done:
                    yield '{"type":"ping"}\n'
                if done and i >= len(run.events):
                    break

        return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})

    app = FastAPI(title="agents-dialpad", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(api)
    app.mount("/", StaticFiles(directory=config.STATIC, html=True), name="static")
    app.state.runs = runs
    app.state.cfg = cfg
    return app

"""HTTP API + static PWA. `create_app()` builds a fresh, independent app (the tests rely on that)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import FileResponse, PlainTextResponse

from pathlib import Path
import sys
from . import applock, config, desk, devices, export, files, gitview, pairing, push, quick, schedules, uploads
from .keepawake import KeepAwake
from .providers import PLANNED, PROVIDERS
from .runs import RunManager
from .store import ID_RE, Store

MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-\[\]/]{0,100}")  # never starts with '-': it is passed as an argument
REQ_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

BASE_MODES = [
    {"id": "readonly", "label": "Read-only (plan)"},
    {"id": "edit", "label": "Can edit files"},
    {"id": "ask", "label": "Ask me before commands"},
]
FULL_MODE = {"id": "full", "label": "Full access (runs commands, no prompts)"}


class ApprovalDecision(BaseModel):
    allow: bool


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
    text: str = Field(default="", max_length=100_000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class PushSubscribe(BaseModel):
    subscription: dict
    label: str = "device"


class PushUnsubscribe(BaseModel):
    endpoint: str


class RevertPath(BaseModel):
    path: str


class NewDevice(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class ImportChat(BaseModel):
    project: str
    session_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    mode: str = "readonly"


def create_app(cfg: dict | None = None, token: str | None = None, keep_awake: KeepAwake | None = None) -> FastAPI:
    if cfg is None or token is None:
        cfg, token = config.load()
    keep_awake = keep_awake or KeepAwake(enabled=bool(cfg.get("keep_awake", True)))
    store = Store(config.DATA / "chats")
    devs = devices.Devices(config.DATA / "devices.json")
    # A phone that subscribed with a device token stops getting pushes once that device is revoked (UI or CLI).
    subs = push.Subscriptions(config.DATA / "push.json", keep=lambda s: not s.get("device") or devs.known(s["device"]))
    idle_mins = float(cfg.get("app_lock_idle_minutes", 5))
    lock_store = applock.LockStore(config.DATA / "lock.json")
    lock_sessions = applock.Sessions(idle_seconds=idle_mins * 60)
    lock_limiter = applock.RateLimiter()
    pending_challenges: dict[str, dict] = {}
    ts_cache: dict = {"at": 0.0, "url": None}

    def allowed_origins() -> list[str]:
        """Loopback plus the Tailscale URL (looked up at most once a minute: it runs a subprocess)."""
        if time.time() - ts_cache["at"] > 60:
            ts_cache["url"] = pairing.tailscale_url(cfg["port"])
            ts_cache["at"] = time.time()
        return applock.get_allowed_origins(cfg["port"], ts_cache["url"])

    def require_unlock(who: str, x_unlock: str | None) -> None:
        """When this identity has a lock, the caller must hold a valid unlock session."""
        if lock_store.has_lock(who) and not (x_unlock and lock_sessions.check(x_unlock, who)):
            raise HTTPException(423, "locked")

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

    async def notify_approval(chat_id: str, run, ev: dict):
        if not subs.all():
            return
        req_id = str(ev.get("id"))
        plain_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
        run.action_tokens[req_id] = token_hash

        try:
            chat = store.get(chat_id)
            prov_name = chat.get("provider", "")
            prov = PROVIDERS.get(prov_name)
            provider_label = prov.label if prov else prov_name.capitalize()
        except KeyError:
            provider_label = "Agent"

        tool_name = (ev.get("tool") or "").lower()
        if tool_name in ("edit", "multiedit", "write"):
            title = f"{provider_label} wants to edit a file"
        else:
            title = f"{provider_label} wants to run a command"

        push_show_commands = bool(cfg.get("push_show_commands", False))
        cmd = ev.get("command") or ""
        body = cmd[:160] if push_show_commands else "Open to see what it wants to do"

        payload = {
            "title": title,
            "body": body,
            "tag": f"approval:{chat_id}:{req_id}",
            "url": f"/#/c/{chat_id}?approval={req_id}",
            "approval": {
                "chat": chat_id,
                "req": req_id,
                "token": plain_token,
                "can_allow": push_show_commands,
            },
        }
        await asyncio.to_thread(push.send_all, subs, payload, config.DATA, cfg["push_contact"])

    def notify_limit(title: str, body: str) -> None:
        """Low-limit alert (C3) as a push notification (B1). Called from the event loop; sends in a worker thread."""
        if not subs.all():
            return
        payload = {"title": title, "body": body, "tag": "limits", "url": "/"}
        asyncio.get_running_loop().run_in_executor(None, push.send_all, subs, payload, config.DATA, cfg["push_contact"])

    async def get_all_limits(refresh: bool = False) -> list[dict]:
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
        return out

    runs = RunManager(
        store,
        cfg["projects"],
        lambda project=None: config.read_instructions(cfg, project),
        lambda: bool(cfg.get("allow_full_access")),
        keep_awake=keep_awake,
        on_finish=notify,
        on_event=notify_approval,
        approval_timeout=lambda: cfg.get("approval_timeout_seconds", 600),
        limit_alert_percent=int(cfg.get("limit_alert_percent", 20)),
        get_limits=get_all_limits,
        notify=notify_limit,
    )
    sched_state = schedules.State(config.DATA / "schedules-state.json")

    loop_holder: list[asyncio.AbstractEventLoop | None] = [None]

    def start_scheduled(s: dict, now: datetime | None = None) -> dict | None:
        prov = PROVIDERS.get(s["agent"])
        if not prov or not prov.available():
            logging.getLogger("agents-dialpad.schedules").warning("Scheduled prompt '%s': agent '%s' not available", s["name"], s["agent"])
            return None
        if s["project"] not in cfg["projects"]:
            logging.getLogger("agents-dialpad.schedules").warning("Scheduled prompt '%s': project '%s' not available", s["name"], s["project"])
            return None
        now_dt = now or datetime.now()
        date_str = now_dt.strftime("%Y-%m-%d")
        chat = store.create(s["agent"], s["project"], s["mode"], s.get("model", ""))
        chat["title"] = f"{s['name']} · {date_str}"
        store.save(chat)
        runs.start(chat, s["prompt"])
        return chat

    def _tick_impl(now_dt: datetime) -> list[str]:
        valid_scheds, _ = schedules.normalize(cfg.get("schedules", []), cfg)
        started = []
        for s in valid_scheds:
            last_run = sched_state.get(s["name"])
            if schedules.is_due(s, now_dt, last_run):
                sched_state.set_run(s["name"], now_dt.strftime("%Y-%m-%d"))
                chat = start_scheduled(s, now_dt)
                if chat:
                    started.append(chat["id"])
        return started

    def scheduler_tick(now: datetime | None = None) -> list[str]:
        now_dt = now or datetime.now()
        loop = loop_holder[0]
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if not in_loop and loop is not None and loop.is_running():
            import concurrent.futures
            fut = concurrent.futures.Future()
            def run_in_loop():
                try:
                    fut.set_result(_tick_impl(now_dt))
                except Exception as ex:
                    fut.set_exception(ex)
            loop.call_soon_threadsafe(run_in_loop)
            return fut.result(timeout=10)
        return _tick_impl(now_dt)

    async def scheduler_loop():
        while True:
            try:
                scheduler_tick()
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        loop_holder[0] = asyncio.get_running_loop()
        app_instance.state.loop = loop_holder[0]
        task = asyncio.create_task(scheduler_loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def modes() -> list[dict]:
        """'Full access' only exists when `"allow_full_access": true` is set in config.json."""
        return BASE_MODES + ([FULL_MODE] if cfg.get("allow_full_access") else [])

    def identity(
        request: Request,
        authorization: str | None = Header(default=None),
        x_unlock: str | None = Header(default=None, alias="X-Unlock"),
    ) -> str:
        supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if supplied and secrets.compare_digest(supplied.encode(), token.encode()):
            who = "owner"
        else:
            dev = devs.match(supplied) if supplied else None
            if dev:
                devs.touch(dev)
                who = dev
            else:
                raise HTTPException(401, "Invalid or missing token")

        path = request.url.path
        if lock_store.has_lock(who):
            if path.rstrip("/") != "/api/info" and not path.startswith("/api/lock"):
                if not x_unlock or not lock_sessions.check(x_unlock, who):
                    raise HTTPException(423, "locked")

        return who

    def owner_only(who: str = Depends(identity)) -> str:
        if who != "owner":
            raise HTTPException(403, "Only the owner token can do this. Use the computer, or `agents-dialpad device`.")
        return who

    api = APIRouter(prefix="/api", dependencies=[Depends(identity)])

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

    def check_project_or_refresh(project: str, not_found_code: int = 404):
        if project not in cfg["projects"] and (cfg.get("scan_documents") or cfg.get("scan_dirs")):
            config.refresh_projects(cfg)
        if project not in cfg["projects"]:
            raise HTTPException(not_found_code, "Unknown project")

    @api.get("/info")
    async def info(who: str = Depends(identity)):
        if cfg.get("scan_documents") or cfg.get("scan_dirs"):
            config.refresh_projects(cfg)

        def provider_modes(p) -> list[dict]:
            all_m = modes()
            if not getattr(p, "supports_ask", False):
                return [m for m in all_m if m["id"] != "ask"]
            return all_m

        disabled = set(cfg.get("disabled_agents", []))
        providers = []
        for p in PROVIDERS.values():
            if p.name in disabled:
                continue
            st = await p.status() if hasattr(p, "status") else {"state": "ready" if p.available() else "not_installed", "note": ""}
            state_val = st.get("state", "unknown")
            is_avail = (state_val != "not_installed")
            models_list = await p.models() if is_avail else []
            providers.append({
                "name": p.name,
                "label": p.label,
                "available": is_avail,
                "status": st,
                "note": st.get("note", ""),
                "models": models_list,
                "modes": provider_modes(p),
            })
        valid_scheds, _ = schedules.normalize(cfg.get("schedules", []), cfg)
        return {
            "providers": providers + [
                {
                    **p,
                    "available": False,
                    "status": {"state": "not_installed", "note": "not yet"},
                    "note": "not yet",
                    "models": [],
                    "modes": [m for m in modes() if m["id"] != "ask"],
                }
                for p in PLANNED
                if p["name"] not in disabled
            ],
            "projects": sorted(list(cfg["projects"]), key=lambda x: (x != "workspace", x.lower())),
            "modes": modes(),
            "usage": runs.usage,
            "keep_awake": keep_awake.enabled,
            "server_os": "windows" if sys.platform.startswith("win") else ("macos" if sys.platform == "darwin" else "linux"),
            "me": who,
            "has_schedules": len(valid_scheds) > 0,
            "disabled_agents": list(cfg.get("disabled_agents", [])),
            "file_viewer": bool(cfg.get("file_viewer", True)),
        }

    @api.get("/pair")
    def pair(_who: str = Depends(owner_only)):
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
    def push_subscribe(body: PushSubscribe, who: str = Depends(identity)):
        try:
            subs.add(body.subscription, body.label, device=None if who == "owner" else who)
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
        return {"providers": await get_all_limits(refresh)}

    @api.get("/usage")
    def get_usage(days: int = 7):
        if not (1 <= days <= 90):
            raise HTTPException(400, "days must be between 1 and 90")
        return {"days": runs.usage_log.summary(days=days)}

    @api.get("/schedules")
    def list_schedules():
        valid_scheds, _ = schedules.normalize(cfg.get("schedules", []), cfg)
        now = datetime.now()
        return [
            {
                "name": s["name"],
                "next_run": schedules.next_run(s, now).isoformat(),
                "last_run": sched_state.get(s["name"]),
                "project": s["project"],
                "agent": s["agent"],
            }
            for s in valid_scheds
        ]

    @api.post("/schedules/{name}/run")
    async def run_schedule_now(name: str):
        valid_scheds, _ = schedules.normalize(cfg.get("schedules", []), cfg)
        s = next((x for x in valid_scheds if x["name"] == name), None)
        if not s:
            raise HTTPException(404, f"No schedule named '{name}'")
        now = datetime.now()
        sched_state.set_run(s["name"], now.strftime("%Y-%m-%d"))
        chat = start_scheduled(s, now)
        if not chat:
            raise HTTPException(400, "Agent or project not available")
        return {"chat_id": chat["id"]}

    @api.get("/chats")
    def list_chats(q: str = Query(default="", max_length=100)):
        chats = store.search(q) if q else store.list()
        for c in chats:
            c["running"] = runs.active(c["id"]) is not None
        return {"chats": chats, "usage": runs.usage}

    @api.get("/projects/{project}/desk-sessions")
    def get_desk_sessions(project: str):
        check_project_or_refresh(project, 404)
        project_path = cfg["projects"][project]
        existing = store.list()
        exclude_ids = {c["session_id"] for c in existing if c.get("session_id")}
        return desk.list_sessions(project_path, exclude_ids=exclude_ids)

    @api.post("/chats/import")
    def import_chat(body: ImportChat):
        check_project_or_refresh(body.project, 400)
        if body.mode not in {m["id"] for m in modes()}:
            raise HTTPException(400, "Unknown mode")
        project_path = cfg["projects"][body.project]
        if not desk.session_belongs_to(project_path, body.session_id):
            raise HTTPException(404, "That desktop session was not found for this project")
        chat = store.create("claude", body.project, body.mode, model="")
        chat["session_id"] = body.session_id
        chat["imported"] = True
        sessions = desk.list_sessions(project_path, exclude_ids=set(), limit=100)
        matching = next((s for s in sessions if s["id"] == body.session_id), None)
        if matching and matching.get("preview"):
            chat["title"] = matching["preview"][:48]
        else:
            chat["title"] = "Desktop session"
        store.save(chat)
        return chat

    @api.post("/chats")
    async def create_chat(body: NewChat):
        if body.provider in set(cfg.get("disabled_agents", [])):
            raise HTTPException(400, "This agent is turned off in config.json")
        prov = PROVIDERS.get(body.provider)
        if not prov or not prov.available():
            raise HTTPException(400, f"Provider '{body.provider}' is not available")
        if hasattr(prov, "status"):
            st = await prov.status()
            if st.get("state") == "not_signed_in":
                raise HTTPException(400, "Codex isn't signed in on the computer. Run `codex login` there, then try again.")
        check_project_or_refresh(body.project, 400)
        if body.mode not in {m["id"] for m in modes()}:
            raise HTTPException(400, "Unknown mode")
        if body.mode == "ask" and not getattr(prov, "supports_ask", False):
            raise HTTPException(400, f"{prov.label} can't ask before commands yet")
        await check_model(prov, body.model)
        return store.create(body.provider, body.project, body.mode, body.model)

    quick_locks: dict[str, asyncio.Lock] = {}

    @api.get("/projects/{project}/commands")
    def list_commands(project: str):
        check_project_or_refresh(project, 404)
        cmds = quick.commands_for(cfg.get("quick_commands", {}), project)
        return [{"index": c["index"], "label": c["label"]} for c in cmds]

    @api.post("/projects/{project}/commands/{index}")
    async def run_command_endpoint(project: str, index: int):
        check_project_or_refresh(project, 404)
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
        check_project_or_refresh(project, 404)
        root = Path(cfg["projects"][project])
        try:
            return await gitview.status(root)
        except FileNotFoundError:
            raise HTTPException(501, "git is not installed on this computer")
        except TimeoutError:
            raise HTTPException(504, "git took too long")

    @api.get("/projects/{project}/changes/diff")
    async def get_project_diff(project: str, path: str = Query(...)):
        check_project_or_refresh(project, 404)
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
        check_project_or_refresh(project, 404)
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

    class SafeFileResponse(FileResponse):
        async def __call__(self, scope, receive, send) -> None:
            try:
                await super().__call__(scope, receive, send)
            except (FileNotFoundError, RuntimeError) as e:
                if isinstance(e, FileNotFoundError) or "does not exist" in str(e):
                    res = PlainTextResponse("File not found", status_code=404)
                    await res(scope, receive, send)
                else:
                    raise

    @api.get("/projects/{project}/files")
    async def list_files_endpoint(project: str, path: str = Query(default="")):
        if not cfg.get("file_viewer", True):
            raise HTTPException(404, "File viewer is disabled")
        check_project_or_refresh(project, 404)
        root = Path(cfg["projects"][project])
        try:
            return await asyncio.to_thread(
                files.list_dir,
                root,
                path,
                data_dir=config.DATA,
                extra_deny=tuple(cfg.get("file_viewer_deny", ())),
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "Directory not found")

    @api.get("/projects/{project}/files/meta")
    async def file_meta_endpoint(project: str, path: str = Query(...)):
        if not cfg.get("file_viewer", True):
            raise HTTPException(404, "File viewer is disabled")
        check_project_or_refresh(project, 404)
        root = Path(cfg["projects"][project])
        try:
            target = files.resolve(
                root,
                path,
                data_dir=config.DATA,
                extra_deny=tuple(cfg.get("file_viewer_deny", ())),
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "File not found")

        if target.is_dir():
            raise HTTPException(400, "That is a folder")

        try:
            st = target.stat()
        except OSError:
            raise HTTPException(404, "File not found")

        kind = files.kind_for(target)
        binary = (kind == "binary")
        previewable = False if binary or (kind in ("image", "pdf") and st.st_size > files.MAX_PREVIEW) else True
        truncated_at = files.MAX_TEXT if kind in ("text", "markdown", "json", "csv") and st.st_size > files.MAX_TEXT else None

        return {
            "name": target.name,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "kind": kind,
            "binary": binary,
            "previewable": previewable,
            "truncated_at": truncated_at,
        }

    @api.get("/projects/{project}/files/content")
    async def file_content_endpoint(project: str, path: str = Query(...), download: int = Query(default=0)):
        if not cfg.get("file_viewer", True):
            raise HTTPException(404, "File viewer is disabled")
        check_project_or_refresh(project, 404)
        root = Path(cfg["projects"][project])
        try:
            target = files.resolve(
                root,
                path,
                data_dir=config.DATA,
                extra_deny=tuple(cfg.get("file_viewer_deny", ())),
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "File not found")

        if target.is_dir():
            raise HTTPException(400, "That is a folder")

        try:
            st = target.stat()
        except OSError:
            raise HTTPException(404, "File not found")

        kind = files.kind_for(target)
        media_type = files.media_type(target, for_view=(download == 0))

        ascii_fallback = "".join(c for c in target.name if 32 <= ord(c) <= 126 and c not in '"\\') or "file"
        encoded = quote(target.name, encoding="utf-8")
        disp_type = "attachment" if download == 1 else "inline"
        content_disposition = f'{disp_type}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'

        headers = {
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
            "Content-Disposition": content_disposition,
        }

        if download == 0 and kind in ("text", "markdown", "json", "csv") and st.st_size > files.MAX_TEXT:
            try:
                with target.open("rb") as f:
                    content = f.read(files.MAX_TEXT)
            except OSError:
                raise HTTPException(404, "File not found")
            headers["X-Truncated"] = "1"
            return Response(content, media_type=media_type, headers=headers)

        return SafeFileResponse(target, stat_result=st, media_type=media_type, headers=headers)

    @api.get("/devices")
    def list_devices(who: str = Depends(identity)):
        return {"devices": devs.list(), "me": who}

    @api.post("/devices")
    def add_device(body: NewDevice, _who: str = Depends(owner_only)):
        try:
            rec, raw_token = devs.add(body.name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        base = pairing.tailscale_url(cfg["port"])
        link = pairing.pair_link(base or f"http://127.0.0.1:{cfg['port']}/", raw_token)
        return {"device": rec, "url": link, "qr": pairing.qr_svg_data_uri(link)}

    @api.delete("/devices/{device_id}")
    def delete_device(device_id: str, _who: str = Depends(owner_only)):
        if not devs.revoke(device_id):
            raise HTTPException(404, "Device not found")
        subs.remove_device(device_id)
        lock_store.reset(device_id)
        lock_sessions.drop_all(device_id)
        return {"ok": True}

    @api.get("/lock/status")
    def lock_status(request: Request, who: str = Depends(identity)):
        host = request.url.hostname or "localhost"
        is_secure = request.url.scheme == "https" or host in ("localhost", "127.0.0.1")
        hint = "" if is_secure else "App lock needs the HTTPS address (Tailscale). Open the app from there."
        return {
            "enabled": lock_store.has_lock(who),
            "available": applock.WEBAUTHN_AVAILABLE,
            "secure_context_hint": hint,
            "credentials": [
                {
                    "id": c["credential_id"],
                    "name": c.get("name", "Passkey"),
                    "created": c.get("created", 0),
                }
                for c in lock_store.list(who)
            ],
            "rp_id": host,
            "idle_minutes": int(cfg.get("app_lock_idle_minutes", 5)),
        }

    @api.post("/lock/register/options")
    async def lock_register_options(
        request: Request,
        who: str = Depends(identity),
        x_unlock: str | None = Header(default=None, alias="X-Unlock"),
    ):
        if not applock.WEBAUTHN_AVAILABLE:
            raise HTTPException(503, "WebAuthn extra not installed")
        require_unlock(who, x_unlock)
        try:
            body = await request.json()
        except Exception:
            body = {}
        rp_id = request.url.hostname or "localhost"
        exclude_creds = [
            applock.PublicKeyCredentialDescriptor(id=applock.b64url_decode(c["credential_id"]))
            for c in lock_store.list(who)
        ]
        opts = applock.generate_registration_options(
            rp_name="agents-dialpad",
            rp_id=rp_id,
            user_id=hashlib.sha256(who.encode("utf-8")).digest(),
            user_name=who,
            user_display_name=who,
            authenticator_selection=applock.AuthenticatorSelectionCriteria(
                authenticator_attachment=applock.AuthenticatorAttachment.PLATFORM,
                resident_key=applock.ResidentKeyRequirement.PREFERRED,
                user_verification=applock.UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=exclude_creds or None,
        )
        chal_id = secrets.token_urlsafe(16)
        now = time.time()
        for k in list(pending_challenges.keys()):
            if pending_challenges[k].get("expires_at", 0) < now:
                pending_challenges.pop(k, None)
        pending_challenges[chal_id] = {
            "challenge": opts.challenge,
            "who": who,
            "rp_id": rp_id,
            "name": body.get("name") or "Passkey",
            "type": "register",
            "expires_at": now + 120,
        }
        raw = json.loads(applock.options_to_json(opts))
        raw["challenge_id"] = chal_id
        return raw

    @api.post("/lock/register/verify")
    async def lock_register_verify(
        request: Request,
        who: str = Depends(identity),
        x_unlock: str | None = Header(default=None, alias="X-Unlock"),
    ):
        if not applock.WEBAUTHN_AVAILABLE:
            raise HTTPException(503, "WebAuthn extra not installed")
        require_unlock(who, x_unlock)
        body = await request.json()
        chal_id = body.get("challenge_id")
        chal = None
        if chal_id and chal_id in pending_challenges:
            cand = pending_challenges[chal_id]
            if cand.get("who") == who and cand.get("type") == "register":
                chal = pending_challenges.pop(chal_id)
        if not chal:
            cred_dict = body.get("credential") if "credential" in body else body
            resp = cred_dict.get("response") or {}
            cd_b64 = resp.get("clientDataJSON")
            if cd_b64:
                try:
                    cd = json.loads(applock.b64url_decode(cd_b64).decode("utf-8"))
                    c_b64 = cd.get("challenge", "")
                    c_bytes = applock.b64url_decode(c_b64)
                    for k, v in list(pending_challenges.items()):
                        if v.get("who") == who and v.get("type") == "register" and v.get("challenge") == c_bytes:
                            chal = pending_challenges.pop(k)
                            break
                except Exception:
                    pass
        if not chal:
            raise HTTPException(400, "Challenge expired or invalid")
        if time.time() > chal.get("expires_at", 0):
            raise HTTPException(400, "Challenge expired")

        cred_dict = body.get("credential") if "credential" in body else body
        origins = await asyncio.to_thread(allowed_origins)
        try:
            ver = applock.verify_registration_response(
                credential=cred_dict,
                expected_challenge=chal["challenge"],
                expected_origin=origins,
                expected_rp_id=chal["rp_id"],
                require_user_verification=True,
            )
        except Exception as e:
            raise HTTPException(400, f"Registration failed: {e}")

        cid = applock.b64url_encode(ver.credential_id)
        pk = applock.b64url_encode(ver.credential_public_key)
        name = body.get("name") or chal.get("name") or "Passkey"
        lock_store.add(who, {
            "credential_id": cid,
            "public_key": pk,
            "sign_count": ver.sign_count,
            "rp_id": chal["rp_id"],
            "name": name,
        })
        token_str, expires_in = lock_sessions.create(who)
        return {"ok": True, "unlock": token_str, "expires_in": expires_in, "credential_id": cid}

    @api.post("/lock/unlock/options")
    async def lock_unlock_options(request: Request, who: str = Depends(identity)):
        if not applock.WEBAUTHN_AVAILABLE:
            raise HTTPException(503, "WebAuthn extra not installed")
        if lock_limiter.is_blocked(who):
            raise HTTPException(429, "Too many failed unlock attempts. Try again later.")
        user_creds = lock_store.list(who)
        if not user_creds:
            raise HTTPException(400, "No passkeys registered for this identity")
        allow_creds = [
            applock.PublicKeyCredentialDescriptor(id=applock.b64url_decode(c["credential_id"]))
            for c in user_creds
        ]
        rp_id = request.url.hostname or user_creds[0].get("rp_id") or "localhost"
        opts = applock.generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow_creds,
            user_verification=applock.UserVerificationRequirement.REQUIRED,
        )
        chal_id = secrets.token_urlsafe(16)
        now = time.time()
        for k in list(pending_challenges.keys()):
            if pending_challenges[k].get("expires_at", 0) < now:
                pending_challenges.pop(k, None)
        pending_challenges[chal_id] = {
            "challenge": opts.challenge,
            "who": who,
            "rp_id": rp_id,
            "type": "auth",
            "expires_at": now + 120,
        }
        raw = json.loads(applock.options_to_json(opts))
        raw["challenge_id"] = chal_id
        return raw

    @api.post("/lock/unlock/verify")
    async def lock_unlock_verify(request: Request, who: str = Depends(identity)):
        if not applock.WEBAUTHN_AVAILABLE:
            raise HTTPException(503, "WebAuthn extra not installed")
        if lock_limiter.is_blocked(who):
            raise HTTPException(429, "Too many failed unlock attempts. Try again later.")
        body = await request.json()
        cred_dict = body.get("credential") if "credential" in body else body
        chal_id = body.get("challenge_id")
        chal = None
        if chal_id and chal_id in pending_challenges:
            cand = pending_challenges[chal_id]
            if cand.get("who") == who and cand.get("type") == "auth":
                chal = pending_challenges.pop(chal_id)
        if not chal:
            resp = cred_dict.get("response") or {}
            cd_b64 = resp.get("clientDataJSON")
            if cd_b64:
                try:
                    cd = json.loads(applock.b64url_decode(cd_b64).decode("utf-8"))
                    c_b64 = cd.get("challenge", "")
                    c_bytes = applock.b64url_decode(c_b64)
                    for k, v in list(pending_challenges.items()):
                        if v.get("who") == who and v.get("type") == "auth" and v.get("challenge") == c_bytes:
                            chal = pending_challenges.pop(k)
                            break
                except Exception:
                    pass
        if not chal:
            lock_limiter.record_fail(who)
            raise HTTPException(400, "Challenge expired or invalid")
        if time.time() > chal.get("expires_at", 0):
            lock_limiter.record_fail(who)
            raise HTTPException(400, "Challenge expired")

        raw_id = cred_dict.get("rawId") or cred_dict.get("id") or ""
        raw_bytes = applock.b64url_decode(raw_id)
        stored = None
        for c in lock_store.list(who):
            if applock.b64url_decode(c["credential_id"]) == raw_bytes:
                stored = c
                break
        if not stored:
            lock_limiter.record_fail(who)
            raise HTTPException(400, "Unknown credential")

        origins = await asyncio.to_thread(allowed_origins)
        try:
            ver = applock.verify_authentication_response(
                credential=cred_dict,
                expected_challenge=chal["challenge"],
                expected_origin=origins,
                expected_rp_id=stored.get("rp_id") or chal["rp_id"],
                credential_public_key=applock.b64url_decode(stored["public_key"]),
                credential_current_sign_count=stored.get("sign_count", 0),
                require_user_verification=True,
            )
        except Exception as e:
            lock_limiter.record_fail(who)
            raise HTTPException(400, f"Authentication failed: {e}")

        lock_store.update_sign_count(stored["credential_id"], ver.new_sign_count)
        lock_limiter.reset(who)
        token_str, expires_in = lock_sessions.create(who)
        return {"ok": True, "unlock": token_str, "expires_in": expires_in}

    @api.delete("/lock/credentials/{credential_id}")
    def lock_delete_credential(
        credential_id: str,
        who: str = Depends(identity),
        x_unlock: str | None = Header(default=None, alias="X-Unlock"),
    ):
        require_unlock(who, x_unlock)
        removed = lock_store.remove(who, credential_id)
        if not removed:
            raise HTTPException(404, "Credential not found")
        if not lock_store.has_lock(who):
            lock_sessions.drop_all(who)
        return {"ok": True}

    @api.post("/lock/lock")
    def lock_drop_session(
        who: str = Depends(identity),
        x_unlock: str | None = Header(default=None, alias="X-Unlock"),
    ):
        if x_unlock:
            lock_sessions.drop_token(x_unlock)
        else:
            lock_sessions.drop_all(who)
        return {"ok": True}

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
        if chat.get("project") in cfg["projects"]:
            chat["project_path"] = str(Path(cfg["projects"][chat["project"]]).resolve())
        return chat

    @api.put("/chats/{chat_id}/uploads")
    async def upload(chat_id: str, request: Request, name: str = Query(..., min_length=1, max_length=200)):
        chat_or_404(chat_id)
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            raise HTTPException(400, "Bad Content-Length") from None
        if declared > uploads.MAX_FILE:
            raise HTTPException(413, "That file is larger than 15 MB")
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > uploads.MAX_FILE:
                raise HTTPException(413, "That file is larger than 15 MB")
        return uploads.save(chat_id, name, bytes(data))

    @api.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        chat_or_404(chat_id)
        run = runs.active(chat_id)
        if run:
            run.stopped = True
            run.kill()
        store.delete(chat_id)
        uploads.remove_all(chat_id)
        return {"ok": True}

    @api.post("/chats/{chat_id}/messages", status_code=202)
    async def send_message(chat_id: str, body: NewMessage):  # async: must run on the event loop
        chat = chat_or_404(chat_id)
        if chat.get("provider") in set(cfg.get("disabled_agents", [])):
            raise HTTPException(400, "This agent is turned off in config.json")
        if runs.active(chat_id):
            raise HTTPException(409, "This chat is already running")
        text = body.text
        if not text.strip():
            if body.attachments:
                text = "See the attached files."
            else:
                raise HTTPException(400, "Message cannot be empty")
        try:
            paths = uploads.resolve(chat_id, body.attachments)
        except ValueError as e:
            raise HTTPException(400, str(e))
        run = runs.start(chat, text, attachments=paths)
        return {"run_id": run.id}

    @api.post("/chats/{chat_id}/stop")
    async def stop(chat_id: str):
        run = runs.active(chat_id)
        if run:
            run.stopped = True
            run.kill()
        return {"ok": True}

    @api.post("/chats/{chat_id}/approvals/{req_id}")
    def decide_approval(chat_id: str, req_id: str, body: ApprovalDecision):
        chat_or_404(chat_id)
        if not REQ_ID_RE.match(req_id):
            raise HTTPException(400, "Invalid request ID")
        latest = runs.runs.get(chat_id)
        if latest and req_id in latest.decided:  # also after the reply finished (a second tap, another device)
            raise HTTPException(409, "Approval request was already decided")
        run = runs.active(chat_id)
        if not run:
            raise HTTPException(404, "No active run for this chat")
        if req_id not in run.pending:
            raise HTTPException(404, "Unknown approval request")
        run.decide(req_id, body.allow)
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

    app = FastAPI(title="agents-dialpad", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(api)

    @app.post("/push-action")
    async def push_action(request: Request):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > 1024:
            raise HTTPException(413, "Body too large")
        raw_body = await request.body()
        if len(raw_body) > 1024:
            raise HTTPException(413, "Body too large")

        try:
            data = json.loads(raw_body)
        except Exception:
            return JSONResponse({"ok": False}, status_code=404)
        if not isinstance(data, dict):
            return JSONResponse({"ok": False}, status_code=404)

        chat_id = data.get("chat")
        req_id = data.get("req")
        token = data.get("token")
        allow = data.get("allow")

        if not isinstance(chat_id, str) or not ID_RE.match(chat_id):
            return JSONResponse({"ok": False}, status_code=404)
        if not isinstance(req_id, str) or not REQ_ID_RE.match(req_id):
            return JSONResponse({"ok": False}, status_code=404)
        if not isinstance(token, str) or not token:
            return JSONResponse({"ok": False}, status_code=404)
        if not isinstance(allow, bool):
            return JSONResponse({"ok": False}, status_code=404)

        try:
            store.get(chat_id)
        except KeyError:
            return JSONResponse({"ok": False}, status_code=404)

        run = runs.active(chat_id)
        if not run:
            latest = runs.runs.get(chat_id)
            if latest and req_id in latest.decided:
                return JSONResponse({"ok": False, "reason": "already_decided"}, status_code=409)
            return JSONResponse({"ok": False}, status_code=404)

        if req_id in run.decided:
            return JSONResponse({"ok": False, "reason": "already_decided"}, status_code=409)

        stored_hash = run.action_tokens.get(req_id)
        if not stored_hash:
            return JSONResponse({"ok": False}, status_code=404)

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not secrets.compare_digest(stored_hash, token_hash):
            return JSONResponse({"ok": False}, status_code=404)

        run.action_tokens.pop(req_id, None)

        ok = run.decide(req_id, allow, by="notification")
        if not ok:
            return JSONResponse({"ok": False, "reason": "already_decided"}, status_code=409)

        return JSONResponse({"ok": True})

    app.mount("/", StaticFiles(directory=config.STATIC, html=True), name="static")
    app.state.runs = runs
    app.state.cfg = cfg
    app.state.sched_state = sched_state
    app.state.lock_store = lock_store
    app.state.lock_sessions = lock_sessions
    app.scheduler_tick = scheduler_tick
    return app

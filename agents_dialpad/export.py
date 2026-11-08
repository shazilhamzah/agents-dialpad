"""Export a conversation as a Markdown file."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone


def filename_for(chat: dict) -> str:
    """Format safe filename for chat export.

    'my-chat-title.md': lowercase, [a-z0-9-], max 40 chars, fallback 'chat.md'.
    """
    title = chat.get("title", "")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:40].rstrip("-")
    if not slug:
        slug = "chat"
    return f"{slug}.md"


def _tool_arg(inp: dict | None) -> str:
    if not inp:
        return ""
    for k in ("command", "CommandLine", "file_path", "path", "pattern", "url", "query", "description"):
        if k in inp and inp[k]:
            v = str(inp[k])
            return v if len(v) <= 80 else v[:79] + "…"
    v = json.dumps(inp)
    return v if len(v) <= 80 else v[:79] + "…"


def chat_to_markdown(chat: dict, agent_label: str) -> str:
    title = chat.get("title", "Chat")
    model = chat.get("model") or "default"
    project = chat.get("project", "")
    created = chat.get("created", 0)
    iso_date = datetime.fromtimestamp(created, timezone.utc).isoformat() if created else ""

    lines = [
        f"# {title}",
        "",
        f"- Agent: {agent_label}   - Model: {model}   - Project: {project}   - Started: {iso_date}",
        "",
    ]

    for m in chat.get("messages", []):
        role = m.get("role")
        if role == "user":
            lines.append("## You")
            lines.append(m.get("text", ""))
            lines.append("")
        elif role == "assistant":
            lines.append(f"## {agent_label}")
            events = m.get("events", [])
            text_blocks = []
            tool_uses = []
            tool_results = {}
            denials = []
            for ev in events:
                t = ev.get("type")
                if t == "text":
                    text_blocks.append(ev.get("text", ""))
                elif t == "tool_use":
                    tool_uses.append(ev)
                elif t == "tool_result":
                    tool_results[ev.get("id")] = ev
                elif t == "done":
                    if ev.get("denials"):
                        denials.extend(ev["denials"])

            if text_blocks:
                lines.append("".join(text_blocks))

            for tu in tool_uses:
                t_id = tu.get("id")
                name = tu.get("name", "")
                arg = _tool_arg(tu.get("input"))
                res = tool_results.get(t_id)
                status = "failed" if (res and res.get("is_error")) else "ok"
                arg_part = f" `{arg}`" if arg else ""
                lines.append(f"- Tool: `{name}`{arg_part} ({status})")

            if denials:
                unique_denials = []
                for d in denials:
                    if d not in unique_denials:
                        unique_denials.append(d)
                lines.append(f"> Blocked (needed approval): {', '.join(unique_denials)}")

            lines.append("")

    return "\n".join(lines).rstrip() + "\n"

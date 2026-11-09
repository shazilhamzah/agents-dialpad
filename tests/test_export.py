"""Unit tests for chat Markdown export."""
from agents_dialpad.export import chat_to_markdown, filename_for


def test_filename_for_various_titles():
    assert filename_for({"title": "Simple Title"}) == "simple-title.md"
    assert filename_for({"title": "Hello / World! 123"}) == "hello-world-123.md"
    assert filename_for({"title": "unicode 🚀 test"}) == "unicode-test.md"
    assert filename_for({"title": "   "}) == "chat.md"
    assert filename_for({}) == "chat.md"
    long_title = "a" * 100
    res = filename_for({"title": long_title})
    assert len(res) <= 43  # 40 chars + .md
    assert res == ("a" * 40) + ".md"


def test_export_markdown_formatting():
    chat = {
        "title": "Debug Issue",
        "provider": "claude",
        "project": "my-project",
        "model": "claude-haiku-5-5",
        "created": 1700000000,
        "messages": [
            {"role": "user", "text": "Can you check the files?"},
            {
                "role": "assistant",
                "events": [
                    {"type": "text", "text": "Sure, let me check."},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "read_file",
                        "input": {"path": "src/main.py"},
                    },
                    {
                        "type": "tool_result",
                        "id": "t1",
                        "text": "code",
                        "is_error": False,
                    },
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "run_command",
                        "input": {"command": "npm test"},
                    },
                    {
                        "type": "tool_result",
                        "id": "t2",
                        "text": "failed",
                        "is_error": True,
                    },
                    {
                        "type": "done",
                        "is_error": False,
                        "denials": ["BashCommand"],
                    },
                ],
            },
        ],
    }
    md = chat_to_markdown(chat, "Claude Code")
    assert md.startswith("# Debug Issue\n\n- Agent: Claude Code")
    assert "- Model: claude-haiku-5-5" in md
    assert "- Project: my-project" in md
    assert "## You\nCan you check the files?" in md
    assert "## Claude Code\nSure, let me check." in md
    assert "- Tool: `read_file` `src/main.py` (ok)" in md
    assert "- Tool: `run_command` `npm test` (failed)" in md
    assert "> Blocked (needed approval): BashCommand" in md

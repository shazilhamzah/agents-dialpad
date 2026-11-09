"""Config (static token, relative project paths) and the chat store (id validation)."""
import json

import pytest

from agents_dialpad import config
from agents_dialpad.store import Store


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("AG_TOKEN", raising=False)
    return tmp_path


def test_token_is_generated_once_and_reused(data_dir):
    _, first = config.load()
    _, second = config.load()
    assert first == second and len(first) >= 32
    assert (data_dir / "token.txt").read_text().strip() == first


def test_env_token_overrides_everything(data_dir, monkeypatch):
    monkeypatch.setenv("AG_TOKEN", "an-explicit-token-123")
    cfg, token = config.load()
    assert token == "an-explicit-token-123" and cfg["_token_source"] == "AG_TOKEN env var"


def test_config_token_is_used(data_dir):
    config.load()  # creates config.json
    path = data_dir / "config.json"
    cfg = json.loads(path.read_text())
    cfg["token"] = "token-from-config-file"
    path.write_text(json.dumps(cfg))
    _, token = config.load()
    assert token == "token-from-config-file"


def test_instructions_are_off_by_default(data_dir):
    cfg, _ = config.load()
    assert cfg["instructions_file"] is None
    assert config.read_instructions(cfg) == ""


def test_short_token_is_rejected(data_dir, monkeypatch):
    monkeypatch.setenv("AG_TOKEN", "short")
    with pytest.raises(SystemExit):
        config.load()


def test_config_file_with_bom_is_accepted(data_dir):
    config.load()
    path = data_dir / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())  # what Windows PowerShell 5.1 writes
    cfg, _ = config.load()
    assert "projects" in cfg


def test_relative_project_paths_resolve_against_the_data_folder(data_dir):
    config.load()
    (data_dir / "config.json").write_text(json.dumps({"projects": {"rel": "workspace", "abs": str(data_dir / "elsewhere")}}))
    cfg, _ = config.load()
    assert cfg["projects"]["rel"] == str(data_dir / "workspace")
    assert cfg["projects"]["abs"] == str(data_dir / "elsewhere")      # absolute paths are kept as written


def test_instructions_are_read_fresh_and_can_be_disabled(tmp_path):
    f = tmp_path / "i.md"
    f.write_text("  be terse  ")
    assert config.read_instructions({"instructions_file": str(f)}) == "be terse"
    f.write_text("changed")
    assert config.read_instructions({"instructions_file": str(f)}) == "changed"
    assert config.read_instructions({"instructions_file": None}) == ""
    assert config.read_instructions({"instructions_file": str(tmp_path / "missing.md")}) == ""


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path)
    chat = s.create("claude", "workspace", "readonly", "some-model")
    assert s.get(chat["id"])["model"] == "some-model"
    assert [c["id"] for c in s.list()] == [chat["id"]]
    s.delete(chat["id"])
    assert not s.exists(chat["id"])


@pytest.mark.parametrize("bad", ["../secret", "..\\..\\config", "abc", "", "g" * 32, "A" * 32])
def test_store_rejects_ids_that_are_not_32_hex_chars(tmp_path, bad):
    s = Store(tmp_path)
    with pytest.raises(KeyError):
        s.get(bad)
    assert s.exists(bad) is False


# --------------------------------------------------------------------------- C6 project instructions
def test_project_objects_are_normalised_to_paths(data_dir):
    config.load()
    (data_dir / "config.json").write_text(json.dumps({
        "projects": {
            "p1": "workspace",
            "p2": {"path": "workspace", "instructions_file": "custom.md"},
        }
    }))
    cfg, _ = config.load()
    assert isinstance(cfg["projects"]["p1"], str)
    assert isinstance(cfg["projects"]["p2"], str)
    assert cfg["projects"]["p2"] == str(data_dir / "workspace")
    assert cfg["_project_instructions"]["p2"] == "custom.md"


def test_project_instructions_follow_the_global_ones(tmp_path):
    g = tmp_path / "global.md"
    g.write_text("global text")
    p = tmp_path / "proj.md"
    p.write_text("project text")

    cfg = {
        "instructions_file": str(g),
        "_project_instructions": {"my-app": str(p)},
    }
    # Combined with blank line
    assert config.read_instructions(cfg, "my-app") == "global text\n\nproject text"
    # Project without instructions gets only global
    assert config.read_instructions(cfg, "other") == "global text"
    # No project passed gets only global
    assert config.read_instructions(cfg) == "global text"


def test_missing_project_instructions_are_ignored(tmp_path):
    g = tmp_path / "global.md"
    g.write_text("global text")
    cfg = {
        "instructions_file": str(g),
        "_project_instructions": {"my-app": str(tmp_path / "nonexistent.md")},
    }
    assert config.read_instructions(cfg, "my-app") == "global text"


def test_projects_without_a_path_are_reported(data_dir):
    config.load()
    (data_dir / "config.json").write_text(json.dumps({
        "projects": {
            "bad": {"instructions_file": "custom.md"},
            "good": "workspace",
        }
    }))
    cfg, _ = config.load()
    assert "bad" not in cfg["projects"]
    assert "good" in cfg["projects"]
    assert "bad" in cfg["_invalid_projects"]


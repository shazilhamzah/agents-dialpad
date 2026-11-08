"""CLI commands, data-folder selection and the generated autostart definitions (macOS launchd / Linux systemd)."""
import json
import plistlib
import sys
from pathlib import Path

import pytest

from agents_dialpad import autostart, cli, config
from agents_dialpad import doctor as doctor_mod


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Isolated data folder. main() rewrites config.DATA and AG_DATA for --data-dir; monkeypatch restores both."""
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    monkeypatch.setenv("AG_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("AG_TOKEN", raising=False)
    return tmp_path / "data"


def run(*argv):
    return cli.main(["--data-dir", str(config.DATA), *argv])


# ------------------------------------------------------------------ init / project
def test_init_creates_the_data_folder_and_adds_projects(data, tmp_path, capsys):
    proj = tmp_path / "app"
    proj.mkdir()
    assert run("init", "--yes", "--project", f"app={proj}") == 0
    raw = json.loads((data / "config.json").read_text())
    assert raw["projects"] == {"workspace": "workspace", "app": str(proj.resolve())}
    assert (data / "chats").is_dir() and (data / "workspace").is_dir()
    assert "agents-dialpad doctor" in capsys.readouterr().out


def test_project_add_list_remove(data, tmp_path, capsys):
    proj = tmp_path / "p"
    proj.mkdir()
    run("init", "--yes")
    run("project", "add", "demo", str(proj))
    run("project", "list")
    assert "demo" in capsys.readouterr().out
    run("project", "remove", "demo")
    assert "demo" not in json.loads((data / "config.json").read_text())["projects"]


@pytest.mark.parametrize("name", ["bad name", "../x", "", "-lead", "a" * 41])
def test_project_names_are_validated(data, tmp_path, name):
    with pytest.raises(SystemExit):
        cli.add_project(name, str(tmp_path))


def test_project_path_must_be_a_folder(data, tmp_path):
    with pytest.raises(SystemExit):
        cli.add_project("x", str(tmp_path / "missing"))


def test_removing_an_unknown_project_fails(data):
    run("init", "--yes")
    with pytest.raises(SystemExit):
        run("project", "remove", "ghost")


# ------------------------------------------------------------------ token
def test_token_is_stable_and_can_be_rotated(data, capsys):
    run("token", "--quiet")
    first = capsys.readouterr().out.strip()
    run("token", "--quiet")
    assert capsys.readouterr().out.strip() == first
    run("token", "--rotate", "--quiet")
    assert capsys.readouterr().out.strip().splitlines()[-1] != first


def test_token_rotation_refuses_when_the_token_is_set_elsewhere(data, monkeypatch):
    run("init", "--yes")
    monkeypatch.setenv("AG_TOKEN", "an-explicit-token-123")
    with pytest.raises(SystemExit):
        run("token", "--rotate")


# ------------------------------------------------------------------ data folder selection
def test_installed_copies_use_the_per_user_folder(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(Path("xdg-home")))
    monkeypatch.setenv("LOCALAPPDATA", str(Path("local-app-data")))
    assert config.platform_data_dir("linux") == Path("xdg-home") / "agents-dialpad"
    assert config.platform_data_dir("windows") == Path("local-app-data") / "agents-dialpad"
    assert config.platform_data_dir("macos") == Path.home() / "Library" / "Application Support" / "agents-dialpad"
    monkeypatch.delenv("AG_DATA", raising=False)
    monkeypatch.setattr(config, "is_source_checkout", lambda: False)
    assert config.default_data_dir() == config.platform_data_dir()


def test_a_git_checkout_keeps_data_next_to_the_code(monkeypatch):
    monkeypatch.delenv("AG_DATA", raising=False)
    monkeypatch.setattr(config, "is_source_checkout", lambda: True)
    assert config.default_data_dir() == config.ROOT / "data"


def test_ag_data_always_wins(monkeypatch):
    monkeypatch.setenv("AG_DATA", "/somewhere/else")
    assert config.default_data_dir() == Path("/somewhere/else")


def test_instructions_resolve_from_data_then_package(data):
    run("init", "--yes")
    assert config.resolve_instructions_path("instructions/caveman.md") == config.PKG / "instructions" / "caveman.md"
    (data / "mine.md").write_text("hi")
    assert config.resolve_instructions_path("mine.md") == data / "mine.md"
    assert "caveman" in config.read_instructions({"instructions_file": "instructions/caveman.md"}).lower()


# ------------------------------------------------------------------ doctor
def test_doctor_fails_without_any_agent_cli(data, monkeypatch):
    run("init", "--yes")
    monkeypatch.setenv("AG_CLAUDE", "definitely-not-installed-claude")
    monkeypatch.setenv("AG_AGY", "definitely-not-installed-agy")
    monkeypatch.setattr(doctor_mod, "tailscale_checks", lambda port: [])
    checks = doctor_mod.run_checks()
    assert any(c.level == "fail" and "agent CLI" in c.label for c in checks)
    assert run("doctor") == 1


def test_doctor_is_happy_with_an_agent_cli(data, monkeypatch):
    run("init", "--yes")
    monkeypatch.setenv("AG_CLAUDE", sys.executable)                    # any real executable that answers --version
    monkeypatch.setenv("AG_AGY", "definitely-not-installed-agy")
    monkeypatch.setattr(doctor_mod, "tailscale_checks", lambda port: [])
    checks = doctor_mod.run_checks()
    assert not any(c.level == "fail" for c in checks)
    assert any(c.label.startswith("Claude Code") and c.level == "ok" for c in checks)


# ------------------------------------------------------------------ autostart definitions
def test_systemd_unit_restarts_and_never_prints_the_token():
    unit = autostart.render_systemd_unit("/usr/bin/python3", "/home/me/.local/share/agents-dialpad")
    assert "ExecStart=/usr/bin/python3 -m agents_dialpad --data-dir /home/me/.local/share/agents-dialpad serve --quiet" in unit
    assert "Restart=always" in unit and "WantedBy=default.target" in unit


def test_systemd_unit_quotes_paths_with_spaces():
    unit = autostart.render_systemd_unit("/opt/my python/bin/python3", "/home/me/my data")
    assert "'/opt/my python/bin/python3'" in unit and "'/home/me/my data'" in unit


def test_launchd_plist_keeps_the_service_alive():
    plist = plistlib.loads(autostart.render_launchd_plist("/usr/bin/python3", "/Users/me/data", "/Users/me/data/gateway.log").encode())
    assert plist["Label"] == autostart.LABEL
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert plist["ProgramArguments"] == ["/usr/bin/python3", "-m", "agents_dialpad", "--data-dir", "/Users/me/data", "serve", "--quiet"]


def test_autostart_dry_run_changes_nothing(data, capsys):
    assert run("autostart", "install", "--dry-run") == 0
    assert "dry run" in capsys.readouterr().out


def test_service_arguments_are_quiet_and_pinned_to_the_data_folder(data):
    args = autostart.service_args()
    assert args[-2:] == ["serve", "--quiet"] and str(config.DATA) in args


def test_plain_command_defaults_to_serve():
    assert "serve" in cli.COMMANDS
    parser = cli.build_parser()
    assert parser.parse_args(["serve", "--port", "9000"]).port == 9000

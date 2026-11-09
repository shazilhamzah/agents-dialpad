"""Unit tests for per-device tokens."""
import json
import pytest
from agents_dialpad import devices


def test_add_stores_hash_only_not_plaintext(tmp_path):
    path = tmp_path / "devices.json"
    devs = devices.Devices(path)

    rec, raw_token = devs.add("Pixel 9")
    assert rec["name"] == "Pixel 9"
    assert len(rec["id"]) == 8
    assert isinstance(raw_token, str) and len(raw_token) > 20

    # Inspect file content directly
    raw_content = path.read_text(encoding="utf-8")
    assert raw_token not in raw_content
    data = json.loads(raw_content)
    assert len(data["devices"]) == 1
    stored = data["devices"][0]
    assert "token_sha256" in stored
    assert stored["token_sha256"] != raw_token

    # Listing devices does not reveal token_sha256
    listed = devs.list()
    assert len(listed) == 1
    assert "token_sha256" not in listed[0]
    assert listed[0]["name"] == "Pixel 9"


def test_match_and_revoke(tmp_path):
    path = tmp_path / "devices.json"
    devs = devices.Devices(path)

    rec, raw_token = devs.add("iPad")
    assert devs.match(raw_token) == rec["id"]
    assert devs.match("wrong-token") is None

    # Revoke
    assert devs.revoke(rec["id"]) is True
    assert devs.match(raw_token) is None
    assert devs.revoke(rec["id"]) is False


def test_name_validation(tmp_path):
    path = tmp_path / "devices.json"
    devs = devices.Devices(path)

    with pytest.raises(ValueError):
        devs.add("")

    with pytest.raises(ValueError):
        devs.add("   ")

    with pytest.raises(ValueError):
        devs.add("x" * 45)

    rec, _ = devs.add("  Clean Name  ")
    assert rec["name"] == "Clean Name"


def test_touch_throttling(tmp_path, monkeypatch):
    import time
    path = tmp_path / "devices.json"
    devs = devices.Devices(path)

    t0 = 1000.0
    monkeypatch.setattr(time, "time", lambda: t0)

    rec, _ = devs.add("MacBook")
    dev_id = rec["id"]

    # Touch 100s later (within 300s throttle) does not write to disk
    monkeypatch.setattr(time, "time", lambda: t0 + 100.0)
    devs.touch(dev_id)

    data1 = json.loads(path.read_text(encoding="utf-8"))
    assert data1["devices"][0]["last_seen"] is None

    # Touch after 350s writes to disk
    t1 = t0 + 350.0
    monkeypatch.setattr(time, "time", lambda: t1)
    devs.touch(dev_id)

    data2 = json.loads(path.read_text(encoding="utf-8"))
    assert data2["devices"][0]["last_seen"] == t1


def test_revoke_from_another_process_applies_at_once(tmp_path):
    """The server's Devices sees a revoke done by the CLI (a second instance) without a restart."""
    path = tmp_path / "devices.json"
    server = devices.Devices(path)
    rec, raw_token = server.add("Phone")
    assert server.match(raw_token) == rec["id"]

    cli = devices.Devices(path)
    assert cli.revoke(rec["id"]) is True

    assert server.match(raw_token) is None
    assert not server.known(rec["id"])
    server.touch(rec["id"])  # a late touch must not write the revoked device back
    assert devices.Devices(path).list() == []


def test_devices_added_by_another_process_are_kept(tmp_path):
    path = tmp_path / "devices.json"
    server = devices.Devices(path)
    first, _ = server.add("Phone")
    second, token = devices.Devices(path).add("Tablet")
    assert server.match(token) == second["id"]
    server.touch(first["id"])
    assert {d["name"] for d in devices.Devices(path).list()} == {"Phone", "Tablet"}

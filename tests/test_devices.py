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

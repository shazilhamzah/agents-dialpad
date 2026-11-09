"""Tests for D5: App lock with WebAuthn passkeys (Face ID, Touch ID, fingerprint)."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents_dialpad import applock, cli, config, doctor
from agents_dialpad.app import create_app
from agents_dialpad.applock import b64url_decode, b64url_encode

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "webauthn" / "recorded.json"


@pytest.fixture
def webauthn_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path: Path):
    cfg = {
        "port": 8787,
        "host": "127.0.0.1",
        "projects": {"test": str(tmp_path)},
        "allow_full_access": False,
        "push_contact": "mailto:test@example.com",
        "app_lock_idle_minutes": 5,
        "_data_dir": str(tmp_path),
        "_token_source": "config",
    }
    config.DATA = tmp_path
    token = "owner-secret-token"
    app = create_app(cfg, token)
    client = TestClient(app, base_url="http://localhost:8787")
    auth_header = {"Authorization": f"Bearer {token}"}
    return {
        "app": app,
        "client": client,
        "auth": auth_header,
        "token": token,
        "data_dir": tmp_path,
        "cfg": cfg,
    }


def _mock_challenges(monkeypatch, fixture: dict):
    orig_gen_reg = applock.generate_registration_options
    orig_gen_auth = applock.generate_authentication_options

    def mock_gen_reg(*args, **kwargs):
        opts = orig_gen_reg(*args, **kwargs)
        opts.challenge = b64url_decode(fixture["reg_challenge_b64"])
        return opts

    def mock_gen_auth(*args, **kwargs):
        opts = orig_gen_auth(*args, **kwargs)
        opts.challenge = b64url_decode(fixture["auth_challenge_b64"])
        return opts

    monkeypatch.setattr(applock, "generate_registration_options", mock_gen_reg)
    monkeypatch.setattr(applock, "generate_authentication_options", mock_gen_auth)


def test_lock_status_when_off_and_extra_missing(env, monkeypatch):
    client = env["client"]
    auth = env["auth"]

    # Lock is off initially
    res = client.get("/api/lock/status", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is False
    assert data["available"] is True
    assert data["credentials"] == []
    assert data["idle_minutes"] == 5

    # When WEBAUTHN_AVAILABLE is False
    monkeypatch.setattr(applock, "WEBAUTHN_AVAILABLE", False)
    res2 = client.get("/api/lock/status", headers=auth)
    assert res2.status_code == 200
    assert res2.json()["available"] is False


def test_register_then_api_requires_unlock(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    # 1. Request options
    opt_res = client.post("/api/lock/register/options", headers=auth, json={"name": "Phone"})
    assert opt_res.status_code == 200
    opts = opt_res.json()
    assert "challenge_id" in opts

    # 2. Register verify with recorded credential
    reg_body = {
        "challenge_id": opts["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
        "name": "My iPhone",
    }
    ver_res = client.post("/api/lock/register/verify", headers=auth, json=reg_body)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["ok"] is True
    unlock_token = ver_data["unlock"]
    assert unlock_token

    # 3. Subsequent API request without X-Unlock -> 423
    chats_locked = client.get("/api/chats", headers=auth)
    assert chats_locked.status_code == 423
    assert chats_locked.json()["detail"] == "locked"

    # 4. Request with X-Unlock -> 200
    headers_with_unlock = {**auth, "X-Unlock": unlock_token}
    chats_unlocked = client.get("/api/chats", headers=headers_with_unlock)
    assert chats_unlocked.status_code == 200


def test_unlock_with_recorded_assertion_returns_a_session(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    # Register first
    opt_res = client.post("/api/lock/register/options", headers=auth, json={})
    client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt_res.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })

    # User is locked out (e.g. new session)
    assert client.get("/api/chats", headers=auth).status_code == 423

    # Unlock ceremony
    auth_opt_res = client.post("/api/lock/unlock/options", headers=auth, json={})
    assert auth_opt_res.status_code == 200
    auth_opts = auth_opt_res.json()

    auth_ver_res = client.post("/api/lock/unlock/verify", headers=auth, json={
        "challenge_id": auth_opts["challenge_id"],
        "credential": webauthn_fixture["auth_credential"],
    })
    assert auth_ver_res.status_code == 200
    session_token = auth_ver_res.json()["unlock"]
    assert session_token

    # Verify session unlocks the API
    res = client.get("/api/chats", headers={**auth, "X-Unlock": session_token})
    assert res.status_code == 200


def test_wrong_origin_is_rejected(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt_res = client.post("/api/lock/register/options", headers=auth, json={})

    # Modify origin in clientDataJSON to an unauthorized origin
    tampered = copy.deepcopy(webauthn_fixture["reg_credential"])
    bad_client_data = json.dumps({
        "type": "webauthn.create",
        "challenge": webauthn_fixture["reg_challenge_b64"],
        "origin": "http://evil.com",
    }).encode("utf-8")
    tampered["response"]["clientDataJSON"] = b64url_encode(bad_client_data)

    ver_res = client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt_res.json()["challenge_id"],
        "credential": tampered,
    })
    assert ver_res.status_code == 400


def test_session_expires_after_idle_time(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt_res = client.post("/api/lock/register/options", headers=auth, json={})
    ver_res = client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt_res.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })
    unlock_token = ver_res.json()["unlock"]
    headers = {**auth, "X-Unlock": unlock_token}

    # Immediately works
    assert client.get("/api/chats", headers=headers).status_code == 200

    # Fast forward time beyond idle_minutes (5 mins = 300s)
    current_time = time.time()
    monkeypatch.setattr(time, "time", lambda: current_time + 305)

    # Now expired -> 423
    assert client.get("/api/chats", headers=headers).status_code == 423


def test_session_of_one_device_does_not_unlock_another(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    # Add two devices
    dev_a = client.post("/api/devices", headers=env["auth"], json={"name": "Phone A"}).json()
    dev_b = client.post("/api/devices", headers=env["auth"], json={"name": "Phone B"}).json()
    token_a = dev_a["url"].split("#token=")[1]
    token_b = dev_b["url"].split("#token=")[1]
    auth_a = {"Authorization": f"Bearer {token_a}"}
    auth_b = {"Authorization": f"Bearer {token_b}"}

    # Device A registers passkey
    opt_a = client.post("/api/lock/register/options", headers=auth_a, json={})
    ver_a = client.post("/api/lock/register/verify", headers=auth_a, json={
        "challenge_id": opt_a.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })
    session_a = ver_a.json()["unlock"]

    # Device A with session_a works
    assert client.get("/api/chats", headers={**auth_a, "X-Unlock": session_a}).status_code == 200

    # Device A without session_a is locked
    assert client.get("/api/chats", headers=auth_a).status_code == 423

    # Device B registers a passkey too so it has lock enabled
    opt_b = client.post("/api/lock/register/options", headers=auth_b, json={})
    client.post("/api/lock/register/verify", headers=auth_b, json={
        "challenge_id": opt_b.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })

    # Device B trying to use Device A's session token -> 423
    res_b = client.get("/api/chats", headers={**auth_b, "X-Unlock": session_a})
    assert res_b.status_code == 423


def test_removing_a_passkey_needs_an_unlocked_session(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt = client.post("/api/lock/register/options", headers=auth, json={})
    ver = client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })
    unlock_token = ver.json()["unlock"]
    cred_id = ver.json()["credential_id"]

    # Without unlock header -> 423
    del_locked = client.delete(f"/api/lock/credentials/{cred_id}", headers=auth)
    assert del_locked.status_code == 423

    # With unlock header -> 200
    del_ok = client.delete(f"/api/lock/credentials/{cred_id}", headers={**auth, "X-Unlock": unlock_token})
    assert del_ok.status_code == 200

    # Now lock is turned off
    status = client.get("/api/lock/status", headers=auth).json()
    assert status["enabled"] is False
    assert client.get("/api/chats", headers=auth).status_code == 200


def test_cli_reset_removes_the_lock_while_the_server_runs(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt = client.post("/api/lock/register/options", headers=auth, json={})
    client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })

    # Locked
    assert client.get("/api/chats", headers=auth).status_code == 423

    # Run CLI reset
    args = argparse.Namespace(action="reset", device=None)
    ret = cli.cmd_lock(args)
    assert ret == 0

    # Server reloads automatically on next request -> now 200
    assert client.get("/api/chats", headers=auth).status_code == 200


def test_revoking_a_device_removes_its_passkeys(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    dev_res = client.post("/api/devices", headers=env["auth"], json={"name": "Tablet"}).json()
    dev_id = dev_res["device"]["id"]
    token = dev_res["url"].split("#token=")[1]
    auth_dev = {"Authorization": f"Bearer {token}"}

    # Register passkey for tablet
    opt = client.post("/api/lock/register/options", headers=auth_dev, json={})
    client.post("/api/lock/register/verify", headers=auth_dev, json={
        "challenge_id": opt.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })

    lock_store = applock.LockStore(env["data_dir"] / "lock.json")
    assert lock_store.has_lock(dev_id) is True

    # Revoke tablet
    del_res = client.delete(f"/api/devices/{dev_id}", headers=env["auth"])
    assert del_res.status_code == 200

    # Device passkeys removed
    assert lock_store.has_lock(dev_id) is False


def test_failed_unlocks_are_rate_limited(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt = client.post("/api/lock/register/options", headers=auth, json={})
    client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })

    bad_assertion = copy.deepcopy(webauthn_fixture["auth_credential"])
    bad_assertion["response"]["signature"] = b64url_encode(b"invalid-signature")

    # 10 failed unlock attempts
    for _ in range(10):
        auth_opt = client.post("/api/lock/unlock/options", headers=auth, json={}).json()
        fail_res = client.post("/api/lock/unlock/verify", headers=auth, json={
            "challenge_id": auth_opt["challenge_id"],
            "credential": bad_assertion,
        })
        assert fail_res.status_code == 400

    # 11th unlock option or verify attempt -> 429
    blocked_opt = client.post("/api/lock/unlock/options", headers=auth, json={})
    assert blocked_opt.status_code == 429
    assert "Too many failed unlock attempts" in blocked_opt.json()["detail"]


def test_lock_routes_and_info_work_while_locked(env, webauthn_fixture, monkeypatch):
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt = client.post("/api/lock/register/options", headers=auth, json={})
    client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })

    # No X-Unlock header provided:
    # 1. /api/info works
    assert client.get("/api/info", headers=auth).status_code == 200

    # 2. /api/lock/status works
    assert client.get("/api/lock/status", headers=auth).status_code == 200

    # 3. /api/lock/unlock/options works
    assert client.post("/api/lock/unlock/options", headers=auth, json={}).status_code == 200

    # 4. other endpoints (/api/chats, /api/devices, etc.) return 423
    assert client.get("/api/chats", headers=auth).status_code == 423
    assert client.get("/api/devices", headers=auth).status_code == 423


def test_doctor_applock_checks(tmp_path):
    # Off when empty
    checks = doctor.applock_checks(tmp_path)
    assert len(checks) == 1
    assert checks[0].level == "ok"
    assert "off" in checks[0].detail

    # Add owner passkey
    store = applock.LockStore(tmp_path / "lock.json")
    store.add("owner", {"credential_id": "c1", "public_key": "pk1"})
    checks = doctor.applock_checks(tmp_path)
    assert checks[0].level == "ok"
    assert "on for owner" in checks[0].detail

    # Add orphan device passkey
    store.add("orphan_dev", {"credential_id": "c2", "public_key": "pk2"})
    checks = doctor.applock_checks(tmp_path)
    warns = [c for c in checks if c.level == "warn"]
    assert len(warns) == 1
    assert "orphan_dev" in warns[0].detail


def test_cannot_register_another_passkey_while_locked(env, webauthn_fixture, monkeypatch):
    """With the lock on, adding a passkey needs a valid unlock, or a stolen bearer token could add its own and unlock."""
    client = env["client"]
    auth = env["auth"]
    _mock_challenges(monkeypatch, webauthn_fixture)

    opt = client.post("/api/lock/register/options", headers=auth, json={})
    ver = client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": opt.json()["challenge_id"],
        "credential": webauthn_fixture["reg_credential"],
    })
    unlock = ver.json()["unlock"]

    # Locked, no X-Unlock: both registration steps are refused
    assert client.post("/api/lock/register/options", headers=auth, json={}).status_code == 423
    assert client.post("/api/lock/register/verify", headers=auth, json={
        "challenge_id": "x", "credential": webauthn_fixture["reg_credential"],
    }).status_code == 423

    # Unlocked: adding another passkey is allowed
    ok = client.post("/api/lock/register/options", headers={**auth, "X-Unlock": unlock}, json={})
    assert ok.status_code == 200


def test_origins_do_not_come_from_the_host_header(env):
    origins = applock.get_allowed_origins(port=8787, tailscale_url="https://box.tail1.ts.net")
    assert "https://box.tail1.ts.net" in origins
    assert "http://localhost:8787" in origins
    assert not any("evil" in o for o in origins)
    assert "http://localhost" not in origins     # no port-less loopback origins

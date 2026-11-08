"""Unit tests for Web Push notifications."""
import pytest
from agents_dialpad import push
from pywebpush import WebPushException


def test_subscriptions_are_deduplicated_by_endpoint(tmp_path):
    subs = push.Subscriptions(tmp_path / "push.json")
    assert subs.all() == []

    sub1 = {
        "endpoint": "https://push.example.com/device1",
        "keys": {"p256dh": "key1", "auth": "auth1"},
    }
    subs.add(sub1, label="phone-1")
    assert len(subs.all()) == 1
    assert subs.all()[0]["label"] == "phone-1"

    # Re-adding same endpoint updates label and deduplicates
    subs.add(sub1, label="phone-1-updated")
    assert len(subs.all()) == 1
    assert subs.all()[0]["label"] == "phone-1-updated"

    # Add different endpoint
    sub2 = {
        "endpoint": "https://push.example.com/device2",
        "keys": {"p256dh": "key2", "auth": "auth2"},
    }
    subs.add(sub2, label="laptop")
    assert len(subs.all()) == 2

    # Reload from disk
    subs2 = push.Subscriptions(tmp_path / "push.json")
    assert len(subs2.all()) == 2


def test_remove_returns_false_for_unknown(tmp_path):
    subs = push.Subscriptions(tmp_path / "push.json")
    assert subs.remove("https://push.example.com/unknown") is False

    sub1 = {
        "endpoint": "https://push.example.com/device1",
        "keys": {"p256dh": "key1", "auth": "auth1"},
    }
    subs.add(sub1, label="phone")
    assert subs.remove("https://push.example.com/device1") is True
    assert subs.remove("https://push.example.com/device1") is False


def test_validate_subscription_rejects_bad_input():
    with pytest.raises(ValueError):
        push.validate_subscription("not a dict")

    # Insecure endpoint (http)
    with pytest.raises(ValueError):
        push.validate_subscription({
            "endpoint": "http://push.example.com/sub",
            "keys": {"p256dh": "k", "auth": "a"},
        })

    # Missing keys
    with pytest.raises(ValueError):
        push.validate_subscription({"endpoint": "https://push.example.com/sub"})

    # Empty p256dh / auth
    with pytest.raises(ValueError):
        push.validate_subscription({
            "endpoint": "https://push.example.com/sub",
            "keys": {"p256dh": "", "auth": "a"},
        })
    with pytest.raises(ValueError):
        push.validate_subscription({
            "endpoint": "https://push.example.com/sub",
            "keys": {"p256dh": "k", "auth": ""},
        })

    # Huge strings
    with pytest.raises(ValueError):
        push.validate_subscription({
            "endpoint": "https://" + ("x" * 1005),
            "keys": {"p256dh": "k", "auth": "a"},
        })
    with pytest.raises(ValueError):
        push.validate_subscription({
            "endpoint": "https://push.example.com/sub",
            "keys": {"p256dh": "k" * 205, "auth": "a"},
        })

    # Valid
    valid = push.validate_subscription({
        "endpoint": "https://push.example.com/sub",
        "keys": {"p256dh": "k", "auth": "a"},
    })
    assert valid["endpoint"] == "https://push.example.com/sub"


def test_payload_is_generic_by_default():
    payload = push.build_payload({"id": "chat1", "title": "My Super Secret Chat"}, None, show_titles=False)
    assert payload == {
        "title": "agents-dialpad",
        "body": "Your reply is ready",
        "tag": "chat1",
        "url": "/#/c/chat1",
    }


def test_payload_can_include_the_title():
    payload = push.build_payload({"id": "chat2", "title": "Implement Feature X"}, None, show_titles=True)
    assert payload["body"] == "Your reply is ready: Implement Feature X"

    # Truncates title to 60 chars
    long_title = "x" * 100
    payload_long = push.build_payload({"id": "chat3", "title": long_title}, None, show_titles=True)
    assert payload_long["body"] == f"Your reply is ready: {'x' * 60}"


def test_payload_for_errors_and_blocked_commands():
    # Error turn
    payload_err = push.build_payload({"id": "c1"}, {"is_error": True}, show_titles=False)
    assert payload_err["body"] == "A reply failed"

    # Denied command turn
    payload_denied = push.build_payload({"id": "c2"}, {"denials": ["rm -rf /"]}, show_titles=False)
    assert payload_denied["body"] == "A reply finished, but a command was blocked"

    # With show_titles
    payload_denied_title = push.build_payload({"id": "c2", "title": "Test Chat"}, {"denials": ["rm"]}, show_titles=True)
    assert payload_denied_title["body"] == "A reply finished, but a command was blocked: Test Chat"


def test_vapid_key_is_created_once_and_reused(tmp_path):
    key1 = push.vapid_public_key(tmp_path)
    pem_path = tmp_path / "vapid_private.pem"
    assert pem_path.exists()
    assert isinstance(key1, str) and len(key1) > 20

    key2 = push.vapid_public_key(tmp_path)
    assert key1 == key2


def test_send_all_removes_gone_subscriptions(monkeypatch, tmp_path):
    subs = push.Subscriptions(tmp_path / "push.json")
    sub1 = {
        "endpoint": "https://push.example.com/device1",
        "keys": {"p256dh": "k1", "auth": "a1"},
    }
    sub2 = {
        "endpoint": "https://push.example.com/device2",
        "keys": {"p256dh": "k2", "auth": "a2"},
    }
    subs.add(sub1, label="phone1")
    subs.add(sub2, label="phone2")
    assert len(subs.all()) == 2

    class FakeResponse:
        status_code = 410

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, ttl):
        if subscription_info["endpoint"] == "https://push.example.com/device1":
            raise WebPushException("Gone", response=FakeResponse())
        # device2 succeeds

    monkeypatch.setattr("pywebpush.webpush", fake_webpush)

    sent = push.send_all(subs, {"title": "hi"}, tmp_path, "mailto:test@example.com")
    assert sent == 1

    remaining = subs.all()
    assert len(remaining) == 1
    assert remaining[0]["endpoint"] == "https://push.example.com/device2"

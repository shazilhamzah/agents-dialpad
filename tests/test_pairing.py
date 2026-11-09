"""Unit tests for QR pairing and URL detection."""
from agents_dialpad import cli, config, pairing


def test_finds_the_https_url_for_our_port():
    status = {
        "Web": {
            "host.ts.net:8443": {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}
            }
        }
    }
    assert pairing.serve_url_from_status(status, 8787) == "https://host.ts.net:8443/"


def test_port_443_has_no_port_in_the_url():
    status = {
        "Web": {
            "host.ts.net:443": {
                "Handlers": {"/": {"Proxy": "http://localhost:8787/"}}
            }
        }
    }
    assert pairing.serve_url_from_status(status, 8787) == "https://host.ts.net/"


def test_other_ports_or_handlers_are_ignored():
    status = {
        "Web": {
            "host.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}},
            "host.ts.net:8444": {"Handlers": {"/api": {"Proxy": "http://127.0.0.1:8787"}}},
        }
    }
    assert pairing.serve_url_from_status(status, 8787) is None


def test_empty_or_malformed_status_returns_none():
    for bad in ({}, {"Web": None}, {"Web": {"x:1": None}}, {"Web": {"no-port": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}}}}):
        assert pairing.serve_url_from_status(bad, 8787) is None


def test_pair_link_puts_the_token_in_the_fragment():
    link = pairing.pair_link("https://host.ts.net:8443/", "secret-token-1234")
    assert link == "https://host.ts.net:8443/#token=secret-token-1234"
    assert "/#token=" in link and "?" not in link


def test_cli_pair_with_url_prints_the_link(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("AG_TOKEN", raising=False)
    rc = cli.main(["--data-dir", str(tmp_path), "pair", "--url", "https://x.example/", "--no-qr"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://x.example/#token=" in out
    assert "Anyone who scans this code can use your agents." in out


def test_cli_pair_writes_a_png(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("AG_TOKEN", raising=False)
    png = tmp_path / "pair.png"
    rc = cli.main(["--data-dir", str(tmp_path), "pair", "--url", "https://x.example/", "--no-qr", "--png", str(png)])
    assert rc == 0
    assert png.read_bytes().startswith(b"\x89PNG")

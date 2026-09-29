"""Tests de proxy.py (protocolo v2)."""
import base64
import ipaddress

import pytest

from src import proxy, secure

SECRET_B64 = base64.b64encode(b"0" * 32).decode("ascii")


def test_parse_allowed_ips():
    nets = proxy._parse_allowed_ips("1.2.3.0/24, 5.6.7.8")
    assert len(nets) == 2


def test_parse_allowed_ips_empty():
    assert proxy._parse_allowed_ips("") == []


def _config(user="admin", password="secret", model="m1", bert="bert1"):
    return {
        "config": {
            "user": user,
            "password": password,
            "model": model,
            "bert_model": bert,
        }
    }


def test_config_ok(monkeypatch):
    monkeypatch.setattr(proxy, "AUTH_USER", "admin")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "m1")
    monkeypatch.setattr(proxy, "BERT_MODEL", "bert1")
    assert proxy._config_ok(_config()) is True


def test_config_wrong_password(monkeypatch):
    monkeypatch.setattr(proxy, "AUTH_USER", "admin")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "m1")
    monkeypatch.setattr(proxy, "BERT_MODEL", "bert1")
    assert proxy._config_ok(_config(password="wrong")) is False


def test_config_wrong_model(monkeypatch):
    monkeypatch.setattr(proxy, "AUTH_USER", "admin")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "m1")
    monkeypatch.setattr(proxy, "BERT_MODEL", "bert1")
    assert proxy._config_ok(_config(model="m2")) is False


def test_config_wrong_bert(monkeypatch):
    monkeypatch.setattr(proxy, "AUTH_USER", "admin")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "secret")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "m1")
    monkeypatch.setattr(proxy, "BERT_MODEL", "bert1")
    assert proxy._config_ok(_config(bert="bert2")) is False


def test_config_missing(monkeypatch):
    monkeypatch.setattr(proxy, "AUTH_USER", "admin")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "secret")
    assert proxy._config_ok({}) is False
    assert proxy._config_ok(None) is False


def test_config_disabled_without_server_fields(monkeypatch):
    monkeypatch.setattr(proxy, "AUTH_USER", "")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "")
    monkeypatch.setattr(proxy, "BERT_MODEL", "")
    assert proxy._config_ok({"config": {}}) is True


def test_ip_allowed(monkeypatch):
    monkeypatch.setattr(proxy, "_ALLOWED_NETS", [ipaddress.ip_network("1.2.3.0/24")])
    assert proxy._ip_allowed("1.2.3.10") is True
    assert proxy._ip_allowed("5.6.7.8") is False


def test_resolve_client_ip_trusted_proxy(monkeypatch):
    monkeypatch.setattr(proxy, "_TRUSTED_NETS", [ipaddress.ip_network("10.0.0.0/8")])
    # peer is a known proxy => honor X-Forwarded-For
    assert proxy._resolve_client_ip("10.0.0.1", "9.9.9.9", None) == "9.9.9.9"
    # peer is NOT a known proxy => ignore X-Forwarded-For
    assert proxy._resolve_client_ip("8.8.8.8", "9.9.9.9", None) == "8.8.8.8"


def test_resolve_client_ip_no_trusted(monkeypatch):
    monkeypatch.setattr(proxy, "_TRUSTED_NETS", [])
    assert proxy._resolve_client_ip("8.8.8.8", "9.9.9.9", None) == "8.8.8.8"


def test_rate_limited(monkeypatch):
    monkeypatch.setattr(proxy, "RATE_LIMIT", 2)
    proxy._rate_hits.clear()
    assert proxy._rate_limited("1.1.1.1") is False
    assert proxy._rate_limited("1.1.1.1") is False
    assert proxy._rate_limited("1.1.1.1") is True


def test_rate_limited_disabled(monkeypatch):
    monkeypatch.setattr(proxy, "RATE_LIMIT", 0)
    assert proxy._rate_limited("1.1.1.1") is False


def test_parse_allowed_ips_ignores_invalid():
    nets = proxy._parse_allowed_ips("no-es-cidr, 1.2.3.4")
    assert nets == [ipaddress.ip_network("1.2.3.4")]


def test_resolve_client_ip_invalid_peer(monkeypatch):
    monkeypatch.setattr(proxy, "_TRUSTED_NETS", [ipaddress.ip_network("10.0.0.0/8")])
    assert proxy._resolve_client_ip("not-an-ip", "9.9.9.9", None) == "not-an-ip"


# ── main(): fail-closed startup ───────────────────────────────────────────
def test_main_invalid_secret_exits(monkeypatch):
    monkeypatch.setattr(proxy, "SECRET", "corto")
    with pytest.raises(SystemExit):
        proxy.main()


def test_main_strict_blocks_insecure(monkeypatch):
    monkeypatch.setattr(proxy, "SECRET", SECRET_B64)
    monkeypatch.setattr(proxy, "ALLOWED_IPS", "")
    monkeypatch.setattr(proxy, "AUTH_USER", "")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "")
    monkeypatch.setattr(proxy, "BERT_MODEL", "")
    monkeypatch.setattr(proxy, "STRICT", True)
    with pytest.raises(SystemExit):
        proxy.main()


@pytest.mark.parametrize("user,password", [("admin", ""), ("", "secret")])
def test_main_strict_requires_both_credentials(monkeypatch, user, password):
    monkeypatch.setattr(proxy, "SECRET", SECRET_B64)
    monkeypatch.setattr(proxy, "ALLOWED_IPS", "1.2.3.4")
    monkeypatch.setattr(proxy, "_ALLOWED_NETS", proxy._parse_allowed_ips("1.2.3.4"))
    monkeypatch.setattr(proxy, "AUTH_USER", user)
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", password)
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "m")
    monkeypatch.setattr(proxy, "BERT_MODEL", "b")
    monkeypatch.setattr(proxy, "RATE_LIMIT", 60)
    monkeypatch.setattr(proxy, "STRICT", True)
    with pytest.raises(SystemExit):
        proxy.main()


def test_invalid_allowed_ips_never_opens_access(monkeypatch):
    monkeypatch.setattr(proxy, "ALLOWED_IPS", "invalid")
    monkeypatch.setattr(proxy, "_ALLOWED_NETS", [])
    assert proxy._ip_allowed("1.2.3.4") is False


def test_main_starts_server(monkeypatch):
    monkeypatch.setattr(proxy, "SECRET", SECRET_B64)
    monkeypatch.setattr(proxy, "ALLOWED_IPS", "1.2.3.4")
    monkeypatch.setattr(proxy, "AUTH_USER", "u")
    monkeypatch.setattr(proxy, "AUTH_PASSWORD", "p")
    monkeypatch.setattr(proxy, "OLLAMA_MODEL", "m")
    monkeypatch.setattr(proxy, "BERT_MODEL", "b")
    monkeypatch.setattr(proxy, "STRICT", False)

    class FakeServer:
        def __init__(self, *args, **kwargs):
            pass

        def serve_forever(self):
            raise SystemExit(0)

    monkeypatch.setattr(proxy, "ThreadingHTTPServer", FakeServer)
    with pytest.raises(SystemExit):
        proxy.main()


def test_replay_cache_used():
    assert isinstance(proxy._replay, secure.ReplayCache)


def test_generic_denial_is_stable():
    assert proxy._GENERIC_DENIAL == {"error": "unauthorized"}


def test_validate_path():
    assert proxy._validate_path("/api/chat") is True
    assert proxy._validate_path("@evil.com/x") is False
    assert proxy._validate_path("//evil.com/x") is False
    assert proxy._validate_path("/api\\chat") is False
    assert proxy._validate_path("/api/chat?x=1") is False
    assert proxy._validate_path("/api/ch\0at") is False
    assert proxy._validate_path("relative") is False


def test_route_allowed_inference():
    assert proxy._route_allowed("POST", "/api/chat") is True
    assert proxy._route_allowed("GET", "/api/tags") is True
    assert proxy._route_allowed("POST", "/v1/chat/completions") is True


def test_route_allowed_management_denied(monkeypatch):
    monkeypatch.setattr(proxy, "ALLOW_MANAGEMENT", False)
    assert proxy._route_allowed("POST", "/api/pull") is False
    assert proxy._route_allowed("DELETE", "/api/delete") is False


def test_route_allowed_management_flag(monkeypatch):
    monkeypatch.setattr(proxy, "ALLOW_MANAGEMENT", True)
    assert proxy._route_allowed("POST", "/api/pull") is True


def test_upstream_url():
    assert proxy._upstream_url("/api/chat") == proxy.OLLAMA_URL + "/api/chat"


def test_upstream_url_rejects_host_trick():
    try:
        proxy._upstream_url("//evil.com/x")
        raise AssertionError("debería rechazar rutas con //")
    except ValueError:
        pass


def test_rate_limited_bounded(monkeypatch):
    monkeypatch.setattr(proxy, "RATE_LIMIT", 1)
    monkeypatch.setattr(proxy, "MAX_RATE_IPS", 2)
    proxy._rate_hits.clear()
    assert proxy._rate_limited("1.1.1.1") is False
    assert proxy._rate_limited("2.2.2.2") is False
    assert proxy._rate_limited("3.3.3.3") is True  # fail-closed al llenarse

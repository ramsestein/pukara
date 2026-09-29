"""Client requests must never bypass pseudonymisation."""

import base64
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import anonymizer, client, local_ollama, privacy


class StubAnon:
    def __init__(self):
        self.values = []

    def reset(self):
        self.values.clear()

    def anonymize(self, text):
        self.values.append(text)
        return f"[TEXT_{len(self.values)}]"

    def deanonymize(self, text):
        for i, value in enumerate(self.values, 1):
            text = text.replace(f"[TEXT_{i}]", value)
        return text


def _post_local(path, body):
    server = ThreadingHTTPServer(("127.0.0.1", 0), local_ollama.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("path", sorted(privacy.INFERENCE_PATHS))
def test_local_inference_blocks_when_anonymizer_missing(monkeypatch, path):
    monkeypatch.setattr(local_ollama, "get_anonymizer", lambda: None)
    monkeypatch.setattr(
        local_ollama, "forward",
        lambda *_args: pytest.fail("request was forwarded without pseudonymisation"),
    )
    status, body = _post_local(path, {"model": "m", "input": "María García"})
    assert status == 503
    assert body == {
        "error": "Request blocked by local privacy protection: anonymizer unavailable",
        "code": "privacy_anonymizer_unavailable",
    }


def test_local_embeddings_are_pseudonymised(monkeypatch):
    anon = StubAnon()
    observed = []
    monkeypatch.setattr(local_ollama, "get_anonymizer", lambda: anon)

    def forward(_method, _path, body):
        observed.append(body["input"])
        return 200, {"embedding": [0.1]}

    monkeypatch.setattr(local_ollama, "forward", forward)
    status, _body = _post_local("/api/embed", {"model": "m", "input": ["María García"]})
    assert status == 200
    assert observed == [["[TEXT_1]"]]


def test_anonymizer_loading_failure_is_cached_and_raised(monkeypatch):
    attempts = []

    def unavailable():
        attempts.append(1)
        raise FileNotFoundError("model missing")

    monkeypatch.setattr(anonymizer, "Anonymizer", unavailable)
    monkeypatch.setattr(anonymizer, "_ANONYMIZER", None)
    monkeypatch.setattr(anonymizer, "_ANONYMIZER_ERROR", None)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="anonymizer unavailable"):
            anonymizer.get_anonymizer()
    assert len(attempts) == 1


def test_local_blocks_when_detection_raises(monkeypatch):
    anon = StubAnon()

    def fail(_text):
        raise RuntimeError("detector failed")

    anon.anonymize = fail
    monkeypatch.setattr(local_ollama, "get_anonymizer", lambda: anon)
    monkeypatch.setattr(
        local_ollama, "forward",
        lambda *_args: pytest.fail("request was forwarded after detector failure"),
    )
    status, _body = _post_local("/api/chat", {
        "model": "m", "messages": [{"role": "user", "content": "María García"}],
    })
    assert status == 503


@pytest.mark.parametrize("extra", [
    {"tools": [{"description": "María García"}]},
    {"metadata": {"patient": "María García"}},
    {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": "data:..."}]}]},
])
def test_local_rejects_unhandled_content(monkeypatch, extra):
    monkeypatch.setattr(local_ollama, "get_anonymizer", StubAnon)
    monkeypatch.setattr(
        local_ollama, "forward",
        lambda *_args: pytest.fail("unsupported content was forwarded"),
    )
    body = {"model": "m", "messages": [{"role": "user", "content": "hola"}]}
    body.update(extra)
    status, response = _post_local("/api/chat", body)
    assert status == 422
    assert response["code"] == "privacy_unsupported_payload"
    assert response["error"].startswith("Request blocked by local privacy protection:")


def test_text_parts_and_completion_restoration():
    anon = StubAnon()
    body = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "María García"},
    ]}]}
    privacy.anonymize_body(anon, body)
    assert body["messages"][0]["content"][0]["text"] == "[TEXT_1]"
    response = {"choices": [{"text": "Hola [TEXT_1]"}]}
    privacy.deanonymize_body(anon, response)
    assert response["choices"][0]["text"] == "Hola María García"


def test_cli_blocks_if_anonymizer_unavailable(monkeypatch, capsys):
    secret = base64.b64encode(b"x" * 32).decode("ascii")
    monkeypatch.setattr(sys, "argv", ["pukara-client", "--url", "http://127.0.0.1:1", "--secret", secret])
    monkeypatch.setattr(anonymizer, "get_anonymizer", lambda: None)
    monkeypatch.setattr(
        client, "secure_request",
        lambda *_args: pytest.fail("CLI forwarded without pseudonymisation"),
    )
    with pytest.raises(SystemExit) as exc:
        client.main()
    assert exc.value.code == 1
    assert "Privacy protection blocked request" in capsys.readouterr().err


def test_cli_pseudonymises_and_restores(monkeypatch, capsys):
    secret = base64.b64encode(b"x" * 32).decode("ascii")
    monkeypatch.setattr(sys, "argv", [
        "pukara-client", "--url", "http://127.0.0.1:1", "--secret", secret,
        "--prompt", "María García",
    ])
    anon = StubAnon()
    monkeypatch.setattr(anonymizer, "get_anonymizer", lambda: anon)

    def secure_request(_secret, _url, _method, _path, body, _config):
        assert body["messages"][0]["content"] == "[TEXT_1]"
        return {"status": 200, "body": {"choices": [{"message": {"content": "Hola [TEXT_1]"}}]}}

    monkeypatch.setattr(client, "secure_request", secure_request)
    client.main()
    assert "Hola María García" in capsys.readouterr().out


def test_gui_never_starts_when_anonymizer_missing(monkeypatch):
    pytest.importorskip("tkinter")
    from src import client_app

    app = client_app.ClientApp.__new__(client_app.ClientApp)
    app.status = lambda _message: None
    app.start_btn = type("Button", (), {"config": lambda self, **_kw: None})()
    app._start_ollama = lambda: pytest.fail("local endpoint started without anonymizer")
    alerts = []
    monkeypatch.setattr(client_app.messagebox, "showerror", lambda *args: alerts.append(args))
    app._on_anon_loaded((None, "missing model"))
    assert app.anon is None
    assert "Privacy protection" in alerts[0][0]
    assert "missing model" in alerts[0][1]


def test_gui_chat_blocks_without_anonymizer():
    pytest.importorskip("tkinter")
    from src import client_app

    app = client_app.ClientApp.__new__(client_app.ClientApp)
    app.anon = None
    with pytest.raises(RuntimeError, match="Privacy protection blocked request"):
        app._do_chat()

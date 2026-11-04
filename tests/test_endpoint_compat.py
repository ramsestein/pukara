"""Compatibilidad del endpoint local corregida en 1.2.1."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import local_ollama, privacy


class EchoAnon:
    def reset(self):
        pass

    def anonymize(self, text):
        return text

    def deanonymize(self, text):
        return text


def _post_raw(path, body):
    server = ThreadingHTTPServer(("127.0.0.1", 0), local_ollama.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers.get("Content-Type"), resp.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()


def _chat_completion(_method, _path, _body):
    return 200, {"id": "c1", "object": "chat.completion", "created": 1, "model": "m",
                 "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": "Hola Ana"}}]}


def test_openai_stream_usa_chunks_con_delta(monkeypatch):
    monkeypatch.setattr(local_ollama, "get_anonymizer", EchoAnon)
    monkeypatch.setattr(local_ollama, "forward", _chat_completion)
    status, ctype, raw = _post_raw("/v1/chat/completions", {
        "model": "m", "stream": True, "messages": [{"role": "user", "content": "hola"}]})
    assert status == 200 and ctype == "text/event-stream"
    events = [line[len("data: "):] for line in raw.split("\n") if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    text = "".join(ch["delta"].get("content", "") for c in chunks for ch in c["choices"])
    assert text == "Hola Ana"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("tools", [[], None])
def test_tools_vacio_se_acepta(monkeypatch, tools):
    seen = []

    def forward(_method, _path, body):
        seen.append(body)
        return 200, {"message": {"role": "assistant", "content": "ok"}, "done": True}

    monkeypatch.setattr(local_ollama, "get_anonymizer", EchoAnon)
    monkeypatch.setattr(local_ollama, "forward", forward)
    status, _ctype, _raw = _post_raw("/api/chat", {
        "model": "m", "tools": tools, "messages": [{"role": "user", "content": "hola"}]})
    assert status == 200
    assert "tools" not in seen[0]


def test_tools_no_vacio_sigue_rechazado():
    with pytest.raises(privacy.UnsupportedPayloadError):
        privacy.anonymize_body(EchoAnon(), {
            "model": "m", "tools": [{"type": "function"}],
            "messages": [{"role": "user", "content": "hola"}]})

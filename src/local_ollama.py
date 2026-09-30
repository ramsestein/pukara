#!/usr/bin/env python3
"""Local server that mimics Ollama and forwards to the encrypted remote proxy.

Run:  python local_ollama.py

It listens on http://127.0.0.1:11434 (Ollama's default port). Tools that
send supported text-only Ollama or OpenAI requests can use the remote model
through this endpoint.
"""
import argparse
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import privacy, secure
from .anonymizer import get_anonymizer

DEFAULT_REMOTE = "https://ollama-sliplane.sliplane.app"
STREAMING_PATHS = {"/api/chat", "/api/generate", "/v1/chat/completions", "/v1/completions"}

# Model-management routes that must never be forwarded to the remote proxy.
_MANAGEMENT_PATHS = {
    "/api/pull", "/api/delete", "/api/create", "/api/copy", "/api/push",
    "/api/blobs",
}

_LOCAL_ORIGIN_HOSTS = ("127.0.0.1", "localhost", "::1")


def _is_management_path(path):
    return path in _MANAGEMENT_PATHS


def read_env(key):
    if os.environ.get(key):
        return os.environ[key]
    try:
        with open(".env", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1]
    except OSError:
        pass
    return ""


REMOTE_URL = (read_env("REMOTE_URL") or DEFAULT_REMOTE).rstrip("/")
SECRET = read_env("ENCRYPTION_SECRET")
AUTH_USER = read_env("AUTH_USER")
AUTH_PASSWORD = read_env("AUTH_PASSWORD")
LOCAL_PORT = int(read_env("LOCAL_PORT") or "11434")
DEFAULT_MODEL = read_env("OLLAMA_MODEL") or "gemma3:270m"
BERT_MODEL = read_env("BERT_MODEL")

if __name__ == "__main__" and not SECRET:
    sys.stderr.write("Missing ENCRYPTION_SECRET in .env\n")
    sys.exit(1)


def _config():
    """Client deployment config to embed inside the encrypted payload.

    The server rejects the request unless every value matches its own
    environment (Ollama model, BERT model, credentials).
    """
    config = {"model": DEFAULT_MODEL, "bert_model": BERT_MODEL}
    if AUTH_USER and AUTH_PASSWORD:
        config["user"] = AUTH_USER
        config["password"] = AUTH_PASSWORD
    return config


def forward(method, path, body=None):
    """Send an encrypted request to the remote proxy; returns (status, body)."""
    inner = {"method": method, "path": path, "body": body, "config": _config()}
    secret = secure.load_secret(SECRET)
    envelope = secure.encrypt_request(secret, json.dumps(inner).encode("utf-8"))
    req_id = secure.b64d(envelope["req_id"])
    data = json.dumps(envelope).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        REMOTE_URL + "/secure/request", data=data, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            resp_envelope = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")

    result = json.loads(
        secure.decrypt_response(secret, resp_envelope, req_id).decode("utf-8")
    )
    return result.get("status", 500), result.get("body")


def _ensure_chat_capability(obj):
    """Some base models (e.g. gemma3:270m) report only 'completion'. We add
    'chat' so the VS Code Ollama extension allows selecting them as chat models.

    We do NOT inject 'tools': if the model does not support them (e.g. the whole
    gemma3 family), the extension would still send them and Ollama would respond
    HTTP 400 'does not support tools'."""
    if isinstance(obj, dict):
        caps = obj.get("capabilities")
        if caps is None:
            obj["capabilities"] = ["chat", "completion"]
        elif isinstance(caps, list):
            for cap in ("chat", "completion"):
                if cap not in caps:
                    caps.append(cap)
    return obj


# ── Client-side pseudonymisation ──────────────────────────────────────────
_ANON_LOCK = threading.Lock()


def _anonymize_body(anon, body):
    """Pseudonymise supported text fields or reject the request."""
    return privacy.anonymize_body(anon, body)


def _deanonymize_body(anon, body):
    """Restore placeholders in supported response fields."""
    return privacy.deanonymize_body(anon, body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[local] %s\n" % (fmt % args))

    def _origin_host(self):
        """Return (origin, hostname) for the request's Origin, or (None, None)."""
        origin = self.headers.get("Origin")
        if not origin:
            return None, None
        try:
            return origin, urllib.parse.urlsplit(origin).hostname
        except ValueError:
            return origin, None

    def _foreign_origin(self):
        """True if the request carries a non-local Origin (browser CSRF)."""
        origin, host = self._origin_host()
        if origin is None:
            return False
        return host not in _LOCAL_ORIGIN_HOSTS

    def _cors_origin(self):
        """Origin to echo into Access-Control-Allow-Origin, or None.

        Never echo arbitrary user input into the header: the value must parse
        to a local host and must not contain CR or LF (HTTP response
        splitting). Requests without an Origin get no CORS header at all.
        """
        origin, host = self._origin_host()
        if origin is None:
            return None
        if "\r" in origin or "\n" in origin:
            return None
        if host not in _LOCAL_ORIGIN_HOSTS:
            return None
        return origin

    def _send(self, code, data, content_type="application/json"):
        if isinstance(data, (dict, list)):
            data = json.dumps(data).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        elif data is None:
            data = b""
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            origin = self._cors_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # The client (e.g. VS Code) closed the connection before finishing.
            # It is harmless and should not print a traceback.
            pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def do_OPTIONS(self):
        if self._foreign_origin():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self._foreign_origin():
            self._send(403, {"error": "forbidden"})
            return
        if self.path == "/":
            self._send(200, "Ollama is running", "text/plain")
            return
        if self.path == "/api/version":
            self._send(200, {"version": "0.34.2"})
            return
        if self.path == "/api/tags":
            status, body = forward("GET", "/api/tags")
            if isinstance(body, dict) and isinstance(body.get("models"), list):
                for m in body["models"]:
                    _ensure_chat_capability(m)
            self._send(status, body)
            return
        if self.path == "/v1/models":
            _, tags_body = forward("GET", "/api/tags")
            models = []
            if isinstance(tags_body, dict) and isinstance(tags_body.get("models"), list):
                for m in tags_body["models"]:
                    models.append(
                        {
                            "id": m.get("name", DEFAULT_MODEL),
                            "object": "model",
                            "created": 0,
                            "owned_by": "ollama",
                        }
                    )
            self._send(200, {"object": "list", "data": models})
            return
        if _is_management_path(self.path):
            self._send(403, {"error": "forbidden"})
            return
        status, body = forward("GET", self.path)
        self._send(status, body)

    def do_POST(self):
        if self._foreign_origin():
            self._send(403, {"error": "forbidden"})
            return
        raw = self._read_body()
        try:
            req_body = json.loads(raw) if raw else {}
        except ValueError:
            req_body = raw.decode("utf-8", "replace")

        if self.path == "/api/show":
            status, body = forward("POST", "/api/show", req_body)
            _ensure_chat_capability(body)
            self._send(status, body)
            return

        if _is_management_path(self.path):
            self._send(403, {"error": "forbidden"})
            return

        want_stream = False
        if isinstance(req_body, dict) and self.path in STREAMING_PATHS:
            want_stream = bool(req_body.get("stream", False))
            req_body = dict(req_body)
            req_body["stream"] = False

        if self.path in privacy.INFERENCE_PATHS:
            _ANON_LOCK.acquire()
            try:
                try:
                    anon = get_anonymizer()
                    if anon is None:
                        raise RuntimeError("anonymizer unavailable")
                    anon.reset()
                    _anonymize_body(anon, req_body)
                except privacy.UnsupportedPayloadError as exc:
                    self._send(422, {
                        "error": f"Request blocked by local privacy protection: {exc}",
                        "code": "privacy_unsupported_payload",
                    })
                    return
                except Exception as exc:  # noqa: BLE001
                    sys.stderr.write(f"[local] anonymizer unavailable: {exc}\n")
                    self._send(503, {
                        "error": "Request blocked by local privacy protection: anonymizer unavailable",
                        "code": "privacy_anonymizer_unavailable",
                    })
                    return
                status, body = forward("POST", self.path, req_body)
                body = _deanonymize_body(anon, body)
            finally:
                _ANON_LOCK.release()
        else:
            status, body = forward("POST", self.path, req_body)

        if want_stream and self.path.startswith("/v1/"):
            # SSE for the OpenAI-compatible endpoint
            payload = "data: " + json.dumps(body) + "\n\ndata: [DONE]\n\n"
            self._send(status, payload, "text/event-stream")
            return
        if want_stream and isinstance(body, dict):
            # Single-line NDJSON (valid for streaming clients)
            self._send(status, json.dumps(body) + "\n", "application/x-ndjson")
            return

        self._send(status, body)


def main():
    parser = argparse.ArgumentParser(description="Ollama local -> proxy remoto cifrado")
    parser.add_argument("--remote", help="URL del proxy remoto (defecto: la de .env)")
    parser.add_argument("--port", type=int, help="Puerto local (defecto 11434)")
    args = parser.parse_args()

    try:
        secure.load_secret(SECRET)
    except secure.InvalidSecretError as exc:
        sys.stderr.write(f"ERROR: ENCRYPTION_SECRET inválida: {exc}\n")
        sys.exit(1)

    global REMOTE_URL, LOCAL_PORT
    if args.remote:
        REMOTE_URL = args.remote.rstrip("/")
    if args.port:
        LOCAL_PORT = args.port

    server = ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), Handler)
    sys.stderr.write(
        f"Ollama local en http://127.0.0.1:{LOCAL_PORT} -> {REMOTE_URL}\n"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()

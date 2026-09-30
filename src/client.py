#!/usr/bin/env python3
"""Test client for the encrypted Ollama proxy (protocol v2)."""
import argparse
import json
import os
import sys
import urllib.request

from . import privacy, secure


def _read_env(key):
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


def load_secret(cli_secret):
    if cli_secret:
        return cli_secret
    value = _read_env("ENCRYPTION_SECRET")
    if value:
        return value
    sys.stderr.write("Missing ENCRYPTION_SECRET (pass it with --secret or in .env)\n")
    sys.exit(1)


def secure_request(secret, base_url, method, path, body, config=None, timeout=600):
    """Encrypted request to the remote proxy. Returns {status, body}."""
    inner = {"method": method, "path": path, "body": body}
    if config:
        inner["config"] = config

    secret_bytes = secure.load_secret(secret)
    envelope = secure.encrypt_request(secret_bytes, json.dumps(inner).encode("utf-8"))
    req_id = secure.b64d(envelope["req_id"])
    data = json.dumps(envelope).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        base_url + "/secure/request",
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_envelope = json.loads(resp.read().decode("utf-8"))
    return json.loads(
        secure.decrypt_response(secret_bytes, resp_envelope, req_id).decode("utf-8")
    )


def main():
    parser = argparse.ArgumentParser(description="Encrypted client for Ollama")
    parser.add_argument(
        "--url",
        default=os.environ.get("OLLAMA_URL", "https://ollama-sliplane.sliplane.app"),
    )
    parser.add_argument("--secret", help="Encryption secret (or ENCRYPTION_SECRET/.env)")
    parser.add_argument("--user", help="Username (or AUTH_USER/.env)")
    parser.add_argument("--password", help="Password (or AUTH_PASSWORD/.env)")
    parser.add_argument("--model", default="gemma3:270m")
    parser.add_argument("--prompt", default="Answer in one sentence: what is Ollama?")
    args = parser.parse_args()

    secret = load_secret(args.secret)
    base = args.url.rstrip("/")

    user = args.user or _read_env("AUTH_USER")
    password = args.password or _read_env("AUTH_PASSWORD")
    model = _read_env("OLLAMA_MODEL") or args.model
    config = {"model": model, "bert_model": _read_env("BERT_MODEL")}
    if user and password:
        config["user"] = user
        config["password"] = password

    # 1) health
    try:
        with urllib.request.urlopen(base + "/health", timeout=30) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        print(f"[OK] Proxy alive: {json.dumps(health)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] /health did not respond: {exc}")

    # 2) chat cifrado
    body = {
        "model": model,
        "messages": [{"role": "user", "content": args.prompt}],
        "stream": False,
    }
    try:
        from .anonymizer import get_anonymizer

        anon = get_anonymizer()
        anon.reset()
        privacy.anonymize_body(anon, body)
    except privacy.UnsupportedPayloadError as exc:
        sys.stderr.write(f"Privacy protection blocked request: {exc}\n")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Privacy protection blocked request: anonymizer unavailable ({exc})\n")
        sys.exit(1)
    result = secure_request(secret, base, "POST", "/v1/chat/completions", body, config)
    if result.get("status") != 200:
        print(f"[FAIL] Server responded {result.get('status')}: {result.get('body')}")
        sys.exit(1)
    content = result["body"]["choices"][0]["message"]["content"]
    content = anon.deanonymize(content)
    print("[OK] Response:")
    print(content)


if __name__ == "__main__":
    main()

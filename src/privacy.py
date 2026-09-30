"""Client-side text protection for supported Ollama and OpenAI requests.

Only text payloads that can be inspected are forwarded. Unsupported string
fields and multimodal content are rejected rather than sent unpseudonymised.
"""

import re

INFERENCE_PATHS = {
    "/api/chat", "/api/generate", "/api/embed", "/api/embeddings",
    "/v1/chat/completions", "/v1/completions", "/v1/embeddings",
}

_TEXT_FIELDS = {"prompt", "input", "system", "template", "suffix"}
_ROLES = {"system", "developer", "user", "assistant", "tool"}
_KEEP_ALIVE = re.compile(r"-?\d+(?:ns|us|µs|ms|s|m|h)?")


class UnsupportedPayloadError(ValueError):
    """A request contains text or media that Pukara cannot protect."""


def _mask_text(anon, value, field):
    if isinstance(value, str):
        return anon.anonymize(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [anon.anonymize(item) for item in value]
    raise UnsupportedPayloadError(f"unsupported {field} content")


def _check_remaining(value, path=()):
    """Reject string fields that were not pseudonymised or verified as syntax."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UnsupportedPayloadError("non-string JSON key")
            if key in {"images", "tools", "tool_calls", "audio", "image_url"}:
                raise UnsupportedPayloadError(f"unsupported {key} content")
            _check_remaining(item, path + (key,))
        return
    if isinstance(value, list):
        for item in value:
            _check_remaining(item, path + ("[]",))
        return
    if not isinstance(value, str):
        return
    if path and path[0] in _TEXT_FIELDS:
        return
    if len(path) >= 3 and path[:2] == ("messages", "[]") and path[2] == "content":
        if len(path) == 3 or path[3:] == ("[]", "text"):
            return
    if path == ("model",):
        return
    if path == ("format",) and value == "json":
        return
    if path == ("encoding_format",) and value in {"float", "base64"}:
        return
    if path == ("think",) and value in {"low", "medium", "high"}:
        return
    if path == ("keep_alive",) and _KEEP_ALIVE.fullmatch(value):
        return
    if path == ("messages", "[]", "role") and value in _ROLES:
        return
    if path == ("messages", "[]", "content", "[]", "type") and value == "text":
        return
    raise UnsupportedPayloadError(f"unsupported string field: {'.'.join(path)}")


def anonymize_body(anon, body):
    """Pseudonymise supported text fields in-place, then reject uncovered text."""
    if not isinstance(body, dict):
        raise UnsupportedPayloadError("request body must be a JSON object")

    messages = body.get("messages")
    if messages is not None:
        if not isinstance(messages, list):
            raise UnsupportedPayloadError("messages must be a list")
        for message in messages:
            if not isinstance(message, dict) or "content" not in message:
                raise UnsupportedPayloadError("unsupported message")
            content = message["content"]
            if isinstance(content, str):
                message["content"] = anon.anonymize(content)
            elif isinstance(content, list):
                for part in content:
                    if (not isinstance(part, dict) or set(part) != {"type", "text"}
                            or part["type"] != "text" or not isinstance(part["text"], str)):
                        raise UnsupportedPayloadError("unsupported message content part")
                    part["text"] = anon.anonymize(part["text"])
            else:
                raise UnsupportedPayloadError("unsupported message content")

    for field in _TEXT_FIELDS:
        if field in body:
            body[field] = _mask_text(anon, body[field], field)

    _check_remaining(body)
    return body


def deanonymize_body(anon, body):
    """Restore placeholders in supported text response fields."""
    if not isinstance(body, dict):
        return body
    message = body.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        message["content"] = anon.deanonymize(message["content"])
    choices = body.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                message["content"] = anon.deanonymize(message["content"])
            if isinstance(choice.get("text"), str):
                choice["text"] = anon.deanonymize(choice["text"])
    if isinstance(body.get("response"), str):
        body["response"] = anon.deanonymize(body["response"])
    return body

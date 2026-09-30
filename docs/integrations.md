# Integrations

The local Ollama endpoint (`python -m src.local_ollama`) exposes a standard
Ollama-compatible API on `http://127.0.0.1:11434`, so you can plug other tools
into Pukara. Supported inference text is pseudonymised on-device and encrypted
in transit.
Inference currently supports text-only chat, generation and embeddings;
requests with tools, images or audio return `422` before forwarding.

## VS Code

Install the
[Ollama](https://marketplace.visualstudio.com/items?itemName=ollama.ollama)
extension and point its endpoint to `http://127.0.0.1:11434`.

## Codex CLI (OpenAI)

Pukara also exposes an OpenAI-compatible endpoint (`/v1/chat/completions`).
Add a provider to `~/.codex/config.toml`:

```toml
model = "llama32"
model_provider = "pukara"

[model_providers.pukara]
name = "Pukara"
base_url = "http://127.0.0.1:11434/v1"
wire_api = "chat"

[model_providers.pukara.models]
llama32 = "llama3.2:3b"
```

## Claude Code (Anthropic)

Claude Code speaks the Anthropic Messages API, which Ollama does not expose
natively. Use a translation router such as
[claude-code-router](https://github.com/musistudio/claude-code-router) pointed
at `http://127.0.0.1:11434/v1`.

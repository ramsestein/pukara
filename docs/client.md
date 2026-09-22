# Client

Pukara ships three client entry points:

| Component | Command | Purpose |
|---|---|---|
| Desktop GUI | `python -m src.client_app` | Configuration, chat, start/stop of the local Ollama |
| CLI | `python -m src.client` | Scriptable encrypted requests |
| Local Ollama endpoint | `python -m src.local_ollama` | Ollama-compatible server for other tools |

## Desktop GUI

The window has three areas:

1. **System status** — environment checks and connection log.
2. **Configuration** (collapsible) — prefilled from `.env`; the public IP is
   auto-detected into `ALLOWED_IPS`.
3. **Chat** (collapsible) — talk to the model.

Flow:

1. Open the app: it checks the BERT model and runs minimal system checks.
2. Click **Detect IP** to refresh the auto-detected IP.
3. Click **Start**: it pings the server (`/health` → 200), starts the local
   Ollama endpoint and loads the anonymizer.
4. Type in the **Message** box and press **Send** (or Enter).
5. **Stop** (or closing the window) stops the local Ollama endpoint.

The chat pipeline is: `anonymize → encrypt → send → receive → decrypt →
deanonymize`.

## CLI

```bash
python -m src.client --url https://your-app.sliplane.app \
  --model llama3.2:3b --prompt "What is Ollama?"
```

## Local Ollama endpoint

```bash
python -m src.local_ollama
```

It listens on `http://127.0.0.1:11434` and forwards (anonymized + encrypted) to
the remote proxy, so any Ollama-compatible tool can use the remote model as if
it were local.

## Restoration mode

When the model edits a placeholder in its answer, Pukara restores it with the
policy selected by `PUKARA_RESTORE_MODE`:

| Mode | Default | Behaviour |
|---|---|---|
| `strict` | **yes** | Restores only placeholders with **both brackets** (`[NOMBRE_1]`). Tolerates case, `**…**`, inner spaces, translated labels, `s`/`'s` suffixes and inner newlines. Never restores a token already present in the original prompt. |
| `lenient` | no | Also recovers `single_bracket` and `lost_brackets`, only at word boundaries and never over a token already present in the original prompt. |

Choose `strict` (default) for VS Code/Codex-style use where code, JSON and SQL
may contain `nombre_1`-like tokens: `strict` alters 0 % of placeholder-free
text, while `lenient` alters tag-like text (adversarial samples: 100 % of texts,
31.8 % of characters). Use `lenient` only for natural-language chat where the
model tends to drop brackets. Full figures in `eval/results/utility.json` and
`docs/metrics.md`.

## Streaming (limitation)

The local endpoint forces `stream=false` upstream and emits a single chunk (SSE
for `/v1/*` endpoints, NDJSON otherwise). True streaming is deliberately not
implemented yet: an anonymized placeholder can be split across streamed chunks,
and deanonymizing partial chunks would leak or corrupt tokens. Future design:
buffer chunks until the streamed JSON array closes (`]`) before deanonymizing,
then re-emit the restored stream chunk by chunk.


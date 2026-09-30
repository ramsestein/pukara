# Client

Pukara ships three client entry points:

| Component | Command | Purpose |
|---|---|---|
| Desktop GUI | `python -m src.client_app` | Configuration, chat, start/stop of the local Ollama |
| CLI | `python -m src.client` | Scriptable encrypted requests |
| Local Ollama endpoint | `python -m src.local_ollama` | Ollama-compatible server for other tools |

All three entry points require the local anonymizer before sending inference
text. A model-loading failure blocks the request. The local endpoint returns
`503` when the anonymizer is unavailable and `422` for unsupported payloads.
Both responses include a `privacy_*` code and an error message explaining that
local privacy protection blocked the request. The GUI and CLI show the same
reason directly.

## Desktop GUI

The window has three areas:

1. **System status** — environment checks and connection log.
2. **Configuration** (collapsible) — prefilled from `.env`; the public IP is
   auto-detected into `ALLOWED_IPS`.
3. **Chat** (collapsible) — talk to the model.

Flow:

1. Open the app: it checks the BERT model and runs minimal system checks.
2. Click **Detect IP** to refresh the auto-detected IP.
3. Click **Start**: it pings the server (`/health` → 200), loads the anonymizer,
   then starts the local Ollama endpoint.
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
the remote proxy, so tools using supported text-only Ollama requests can use
the remote model as if it were local.

Text in chat messages, generation prompts and embedding inputs is
pseudonymised. Text-only content parts are supported. Requests containing
images, audio, tool calls or other string fields that Pukara cannot inspect
are rejected before forwarding. Model-listing and metadata requests do not
contain inference text.

## Restoration

When the model edits a placeholder in its answer, Pukara restores it with a
single policy (`strict`): both brackets are required (`[NOMBRE_1]`). It
tolerates case, `**…**`, inner spaces, translated labels, `s`/`'s` suffixes and
inner newlines, and never restores a token already present in the original
prompt.

`strict` alters 0 % of placeholder-free text, even on adversarial tag-like
tokens (`nombre_1`, `[ID_2`, `FECHA_3]`). `single_bracket` / `lost_brackets`
edits are **not** recovered and are reported as honest restoration failures.
Full figures in `eval/results/utility.json` and `docs/metrics.md`.

## Streaming (limitation)

The local endpoint forces `stream=false` upstream and emits a single chunk (SSE
for `/v1/*` endpoints, NDJSON otherwise). True streaming is deliberately not
implemented yet: an anonymized placeholder can be split across streamed chunks,
and deanonymizing partial chunks would leak or corrupt tokens. Future design:
buffer chunks until the streamed JSON array closes (`]`) before deanonymizing,
then re-emit the restored stream chunk by chunk.

# Installation

## Server (Docker)

1. Copy and edit the environment template:

   ```bash
   cp .env.example .env
   ```

   Set `ENCRYPTION_SECRET`, `AUTH_PASSWORD` and `ALLOWED_IPS` to values for
   your deployment. Docker Compose requires these three values. It uses
   `AUTH_USER=admin`, `RATE_LIMIT=60` requests/minute per client IP and
   `STRICT=1` by default. Set `TRUSTED_PROXIES` to the CIDRs of a reverse
   proxy you actually trust; leave it empty for a direct connection. An
   `AUDIT_LOG` path needs a writable mounted directory (or `/tmp`, which is
   temporary in the supplied container).

   Credentials, `OLLAMA_MODEL` and `BERT_MODEL` travel inside the encrypted
   protocol-v2 request and must match the server configuration. Pin the
   client model with `BERT_MODEL_SHA256` to detect tampering.

2. Build and run:

   ```bash
   docker compose up --build
   ```

   The encrypted proxy listens on port `8000`. Ollama stays internal
   (`127.0.0.1:11434`, never exposed).

## Client

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   pip install -r requirements-client.txt
   ```

   The second file installs `torch`, `transformers` and `huggingface_hub`,
   which are required only for the on-device BERT anonymization. The server
   does not need them.

2. Copy and edit the environment template:

   ```bash
   cp .env.example .env
   ```

   Set `REMOTE_URL` (the server URL), the same `ENCRYPTION_SECRET` as the
   server, and `AUTH_USER` / `AUTH_PASSWORD`. `OLLAMA_MODEL` and `BERT_MODEL`
   must also match the server (they are part of the credential-encryption key).

3. Download the BERT model. If Hugging Face requires authentication for your
   access, first log in:

   ```bash
   huggingface-cli login
   ```

   Then either let the desktop client download it on first launch, or place it
   manually under `models/bsc-bio-ehr-es-carmen-anon/`.

   The CLI and local endpoint block inference requests if the model cannot be
   loaded. Install the client dependencies and model before using either one.

4. Run the desktop client:

   ```bash
   python -m src.client_app
   # or run_client.bat (Windows) / run_client.sh (Linux)
   ```

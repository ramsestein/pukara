# Contributing

Thanks for your interest in Pukara.

## Development environment

```bash
# 1. Clone
git clone <repo-url>
cd pukara

# 2. Create a virtual environment and install dev dependencies
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements-dev.txt

# 3. Copy the example configuration
cp .env.example .env   # edit with your values
```

> Note: `torch` and `transformers` (in `requirements-client.txt`) are only
> needed for BERT anonymization. The unit tests do not require them.

## Running the tests

```bash
python -m pytest -q
```

Tests cover:

- `secure.py` — protocol v2 encryption/decryption, freshness, anti-replay and key derivation.
- `anonymizer.py` — label mapping, regex detection and reversible placeholders.
- `proxy.py` — config matching, route allowlist and IP allowlist.
- `local_ollama.py` — request/response pseudonymisation.

## Running the server locally

```bash
docker compose up --build
```

## Conventions

- Python 3.9+.
- Secrets go in `.env` (never committed) or environment variables, not in code.
- Run `python -m pytest -q` before opening a pull request.

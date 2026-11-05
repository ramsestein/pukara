# Pukara

<p align="center">
  <img src="docs/image.png" alt="Pukara logo" width="220">
</p>

[![CI](https://github.com/ramsestein/pukara/actions/workflows/ci.yml/badge.svg)](https://github.com/ramsestein/pukara/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)]()
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.2.1-orange)]()

A privacy-first, self-hosted gateway for local large language models
([Ollama](https://ollama.com)). Pukara runs a Dockerized Ollama server behind an
application-layer encrypted proxy, and ships a desktop client that
**pseudonymises sensitive entities on-device** (BERT + regex) before anything
leaves the machine.

The name *Pukara* (Quechua for "fortress") plays on Ollama's alpaca: a small,
resilient stronghold around your model.

## Software metadata

| Field | Value |
|---|---|
| Name | Pukara |
| Version | 1.2.1 |
| License | [MIT](LICENSE) |
| Language | Python 3.9+ |
| Dependencies | `cryptography`, `numpy` (core); `torch`, `transformers`, `huggingface_hub` (client) |
| Repository | https://github.com/ramsestein/pukara |
| CI | [GitHub Actions](.github/workflows/ci.yml) |
| DOI | https://doi.org/10.5281/zenodo.23938794 (Zenodo release `v1.2.1`; `v1.2.0`: https://doi.org/10.5281/zenodo.23050229) |

## Abstract

Pukara addresses the gap between self-hosted LLMs and privacy. It encrypts the
whole client–server channel with protocol v2 (pre-shared key, AES-256-GCM with
HKDF-SHA256, direction-separated keys, server-clock freshness and anti-replay),
and **pseudonymises personal data on the client** before transmission:
detected entities are replaced by reversible placeholders and the
placeholder→text map never leaves the client. The sender's data remain personal
to the client; whether the transmitted text is anonymous for the recipient
depends on residual re-identification risk (see the threat model and
`docs/metrics.md`). It is designed for **Spanish** clinical text and is
model-agnostic (swap `BERT_MODEL` for another language).

## Motivation and significance

- Local models are increasingly self-hosted, but the transport and the payload
  are rarely protected end-to-end.
- Clinical and personal Spanish text has few ready-to-use pseudonymisation tools.
- Pukara packages encryption + on-device NER pseudonymisation + a local
  endpoint that implements a text-only subset of the Ollama and OpenAI APIs:
  tools that send supported text-only requests can connect by pointing to it.
  Requests with content Pukara cannot protect (tool definitions, images,
  audio, unsupported fields) are rejected with HTTP 422 instead of being sent
  unprotected; streaming requests receive the full response in one chunk.

## Software architecture

```mermaid
flowchart LR
    subgraph Client
      GUI[Desktop GUI] --> AN[Pseudonymiser BERT + regex]
      LO[Virtual Ollama :11434] --> AN
    end
    AN -- "protocol v2 encrypted envelope over HTTPS" --> PX[Proxy :8000]
    PX -- "local HTTP" --> OL[Ollama :11434]
```

Protocol v2 (`src/secure.py`, see `docs/dev/adr-001-protocol.md`):

- `ENCRYPTION_SECRET` is a 32-byte pre-shared key (generate with
  `python -m src.keygen`).
- Direction-separated keys: `HKDF-SHA256(secret, "pukara/v2/c2s")` and
  `HKDF-SHA256(secret, "pukara/v2/s2c")`.
- Every envelope carries `{v, ts, req_id, nonce, ciphertext}`; the AAD binds
  version, direction, timestamp and request id.
- The server rejects timestamps outside `MAX_SKEW`, replays via a bounded
  fail-closed `req_id` cache, and responses are bound to the request id.
- Credentials and the deployment configuration (`user`, `password`, `model`,
  `bert_model`) travel inside the encrypted payload and must all match the
  server, or the request is rejected.

See [`docs/installation.md`](docs/installation.md) and
[`docs/client.md`](docs/client.md) for the full details.

## Functionality

- Dockerized Ollama server behind an encrypted proxy (protocol v2, IP allowlist,
  route allowlist, rate limiting, anti-replay, body limit).
- On-device pseudonymisation (BERT `bsc-bio-ehr-es-carmen-anon` + regex).
- Desktop GUI with auto-detected IP and start/stop of the local endpoint.
- Ollama/OpenAI-compatible local endpoint for external tools.

## Installation

Installation (server and client) is documented in
[`docs/installation.md`](docs/installation.md).

## Usage

- Desktop client and CLI: [`docs/client.md`](docs/client.md).
- VS Code, Codex CLI and Claude Code: [`docs/integrations.md`](docs/integrations.md).

## Security

See [`docs/threat-model.md`](docs/threat-model.md) for the threat model and
[`docs/SECURITY.md`](docs/SECURITY.md) for the security model, hardening and how to
report vulnerabilities.

## Evaluation

Pseudonymisation metrics are regenerated from versioned JSON files with
`make eval` and reported in [`docs/metrics.md`](docs/metrics.md). The reported
split is **MEDDOCAN `test`** (250 documents, out-of-distribution, run once).
The table compares Pukara with two **Presidio standalone baselines** using the
same evaluator (full numbers and the per-class table are in `docs/metrics.md`):

| Metric (MEDDOCAN test) | Pukara | Presidio (OOTB) | Presidio (ES) |
|---|---|---|---|
| Word F1 | 88.5 % | 59.1 % | 59.6 % |
| Span relaxed F1 | 85.7 % | 59.1 % | 57.2 % |
| PHI neutralization | 93.5 % | 56.2 % | 62.3 % |
| Leakage direct | 1.6 % | 100.0 % | 99.2 % |
| Leakage wide | 5.2 % | 100.0 % | 99.2 % |
| Over-redaction (non-PHI tokens altered) | 1.6 % | 2.9 % | 4.9 % |

Over-redaction is the domain-agnostic metric that measures how much non-PHI
text the detector rewrites; see `docs/metrics.md` for its bootstrap CI and the
per-component breakdown. Leakage counts documents with an identifier that has
no overlapping replacement; under a strict criterion (every annotated
character removed), 80.7 % of direct identifiers are fully removed, 19.1 %
partially, and alphanumeric fragments of direct identifiers remain in 219/250
documents (see `docs/metrics.md`).

These figures come from the v1.2.1 re-run. Earlier (v1.2.0) results were
produced in an environment where BERT only processed the first 512-token
window of each document; they are archived with the evidence in
[`eval/results/archive_2026-09/`](eval/results/archive_2026-09/README.md).

CARMEN-I is not reported in v1.2.1: the model was fine-tuned on it, and the
corpus requires credentialed access (PhysioNet). Researchers with access can
run `make eval-carmen` with the corpus under `data/carmen`.

## Limitations

- **No forward secrecy.** The protocol uses a pre-shared key: whoever obtains
  `ENCRYPTION_SECRET` can decrypt recorded traffic.
- **Detector recall is < 1.** Missed direct identifiers are transmitted in the
  clear; measured document-level leakage on MEDDOCAN test is 1.6 % (direct,
  CI 0.4–3.2 %) / 5.2 % (wide, CI 2.8–8.0 %), and partial fragments of direct
  identifiers remain in most documents — see `docs/metrics.md`.
- **Residual leakage** is a document-level mean with a bootstrap CI; the point
  estimate alone understates the per-document variance (see the CI in
  `docs/metrics.md`).
- **Over-redaction.** The detector rewrites 1.6 % of non-PHI tokens on test
  (CI 1.5–1.7 %), mostly BERT fragments and `name` rules firing on title-case
  clinical headers — see `docs/dev/eval-diagnosis.md`.
- **Restoration policy.** Round-trip without an LLM is exact on the evaluated
  samples (57/57 controlled texts; 250/250 MEDDOCAN test documents). Restoration of an
  LLM-edited placeholder requires both brackets (`strict`); single/lost
  brackets are not recovered and are reported as honest failures.
  Placeholder-free text is never altered (0 %, even on adversarial tag-like
  tokens). See `docs/client.md`.
- **Domain-concept retention is not measured by design.** Pukara is not
  clinical-domain-specific, so a clinical-concept retention metric would bias
  the evaluation to that domain; the domain-agnostic over-redaction metric is
  used instead.
- **Out-of-distribution evaluation.** The BERT model is fine-tuned on
  CARMEN-I; MEDDOCAN is a different clinical corpus (neutralization 93.5 %).
- **Corpus mismatch.** MEDDOCAN consists of structured clinical cases with a
  header block; results may not transfer to discharge letters or user prompts.
- **Traffic analysis is not mitigated** (sizes and timings are visible).
- **Re-identification via quasi-identifiers** is possible even when every direct
  identifier is replaced.
- **Streaming is not implemented** (see `docs/client.md`): the local endpoint
  forces `stream=false`.
- **A compromised client is out of scope** (it holds the original text, the map
  and the key).
- **Text-only request support.** The local endpoint rejects images, audio,
  tool calls and unrecognised string fields rather than forwarding content it
  cannot pseudonymise. Inference is blocked when the client model is unavailable.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests cover `secure.py`, `proxy.py`, `anonymizer.py` and `local_ollama.py`
without downloading the BERT model, plus proxy↔client integration against a
fake Ollama. CI enforces ≥85% coverage on `secure.py` and `proxy.py`, `ruff`,
and `pip-audit`.

## Citation

If you use Pukara, please cite it using [`CITATION.cff`](CITATION.cff).

## License

MIT. See [`LICENSE`](LICENSE).

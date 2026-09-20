# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - unreleased

### Breaking

- **Protocol v2 replaces v1.** v2 is a pre-shared-key protocol: HKDF-SHA256
  with direction-separated keys (`pukara/v2/c2s`, `pukara/v2/s2c`), canonical
  AAD, server-clock freshness (`MAX_SKEW`), per-request `req_id` anti-replay
  cache (fail-closed), and responses bound to the request. There is **no
  backward-compatible fallback** to v1 (a fallback would be a downgrade
  vector). Old `ENCRYPTION_SECRET` values are rejected.
- The "auth layer" (parallel envelope keyed by model names + password) is
  removed. Credentials and the deployment configuration (`user`, `password`,
  `model`, `bert_model`) now travel inside the encrypted payload and are
  compared with `hmac.compare_digest`; every value must match or the proxy
  rejects the request.

### Security

- Fix freshness check: the server compares `ts` against its own clock.
- Fix reflection: separate keys per direction plus response/request binding.
- Fix SSRF: upstream URLs are built with `urllib.parse` and validated against
  `OLLAMA_URL`.
- Fix error oracle: one generic response for tag/freshness/replay/config
  failures; the cause goes only to the audit log.
- Hardening: `(method, path)` allowlist, request-body limit (10 MB default),
  bounded rate/replay structures, fail-closed startup with `STRICT=1`,
  `/health` returns only `{"ok": true}`, audit log with `req_id`/reason/size.
- Restrict the local endpoint CORS to local origins and deny model-management
  routes.
- Pin the BERT model: repo `BSC-NLP4BIA/bsc-bio-ehr-es-carmen-anon`, revision
  `83db1112c37c7ef527a9ba6d6b4d1be18b4bca9b`, weights SHA-256
  `883c7c2c63d01da8af3ea12a8b22237f2896b0ce`.

### Added

- `python -m src.keygen` (or the `pukara-keygen` entry point).
- Evaluation harness under `eval/`; `make eval` regenerates `docs/metrics.md`.
- Threat model (`docs/threat-model.md`) and ADR
  (`docs/dev/adr-001-protocol.md`).

### Evaluation (second pass)

- Evaluation protocol frozen in `eval/PROTOCOL.md`; MEDDOCAN `train` (500) is
  burned (regexes were derived from it), `dev` (250) is for ablations, and
  `test` (250) is the only reported split, run once (`eval-frozen-v2`).
- Detector fixes: phone regex bounded to Spanish formats, concrete identifier
  formats (DNI/NIE with valid letter, NHC, CIP, SS), BERT/regex disagreement
  rule, signature name triggers, hospital regex with case-sensitive proper noun,
  whitelist pruning (`ANA`).
- Tolerant placeholder restoration (`deanonymize`) with property tests
  (Hypothesis).
- Microsoft Presidio as an optional third detector component
  (`PUKARA_ENABLE_PRESIDIO=1`); the standalone Presidio baseline is referenced
  from `ramsestein/presidio_carmen`.

## [0.1.0] - 2026-09-18

- Initial release.

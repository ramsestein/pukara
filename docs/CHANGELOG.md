# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [1.2.1] - unreleased

### Fixed

- **BERT window coverage (evaluation and production).** Results produced in
  September 2026 came from an environment in which BERT only processed the
  first 512-token window of each text. `Anonymizer.check_bert_coverage` now
  blocks (fail-closed) any text not fully covered by the BERT windows. All
  results in `eval/results` were regenerated with the same frozen detector
  configuration; the old files are archived in `eval/results/archive_2026-09/`
  with the evidence.
- **Restoration in a single pass.** Restored text is never reparsed, so a
  later placeholder can no longer consume a restored character as a plural
  suffix (`[NOMBRE_1][LUGAR_1]` → "Anasan", previously "Anaan").
- **Escape map per request.** Escape markers are unique across all messages of
  a request and the map is no longer overwritten or cleared by later messages
  (ordinary text such as "Hospital 12" / "hora 14" could be restored in the
  wrong place).
- **OpenAI streaming.** Streaming chat requests now receive
  `chat.completion.chunk` events with `delta` (previously OpenAI clients read
  an empty reply). The response is still delivered in a single chunk.
- **Empty tool lists.** `tools: []` / `null` (sent by the official Ollama
  Python client) is accepted; non-empty tool definitions are still rejected.

### Added

- `requirements-client.lock` (reference environment) and an `environment`
  block with library versions in every results JSON.
- Complementary evaluation metrics in `eval/meddocan.py`: strict per-annotation
  coverage and round-trip without an LLM.

### Changed

- Author metadata (CITATION.cff, .zenodo.json, pyproject.toml): names without
  accents, second surnames, Universitat de Barcelona affiliations.

## [1.2.0] - 2026-09-30

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

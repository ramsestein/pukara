# Pukara — Consolidated audit (second pass)

**Status:** rewritten from the current repository state. The deleted version is
not restored; it is rebuilt with `git show 8754c1b:docs/dev/audit.md` only as
reference.
**Date:** 2026-09-19.
**Audited commit:** `cd095c7` (`Separate ML stack from client and audit only the
core with pip-audit`), branch `main`.
**Scope:** `src/`, `eval/`, `docs/`, `tests/`, `lista_blanca.txt`,
`requirements*.txt`, `Makefile`.

The original audit (phase 0, on `7ecaff2`) is integrated here as §1. This
second pass adds the findings from reading the results history commit by commit
and from reviewing the detector and harness with evaluation discipline (§2).

---

## 1. Original findings: status

| ID | Finding | Status |
|---|---|---|
| A1 | Fail-open IP allowlist and credentials | **Resolved** `84ccf5e` (phase 2): fail-closed startup + `STRICT=1`. |
| A2 | Error oracle distinguishes failure causes | **Resolved** `606ccec` (phase 1): single generic response. |
| A3 | Audit log lacks `req_id`, reason and size | **Resolved** `84ccf5e`. |
| A4 | Response not bound to request (substitution) | **Resolved** `606ccec`: AAD binds the response to `req_id`. |
| A5 | Unbounded upstream response read | **Resolved** `84ccf5e`: body limit and timeouts. |
| A6 | `verify_model_hash` fail-open | **Partial.** Hash and revision are pinned in `eval/common.py` (`MODEL_META`); the loader in `src/anonymizer.py` still returns `True` when `BERT_MODEL_SHA256` is unset. Documented as residual risk in `docs/SECURITY.md`. |
| A7 | Local endpoint with open CORS and no auth | **Resolved** `84ccf5e`: CORS restricted to local origins. |
| A8 | Arbitrary path forwarding on the local endpoint | **Resolved** `84ccf5e`: management routes denied. |
| A9 | Round-trip not guaranteed for adversarial input | **Resolved this pass (Phase D):** `deanonymize` rewritten with tolerant regex restoration and a property test. |
| A10 | Whitelist inconsistent between BERT and regex | **Resolved** `84ccf5e` (pruning of doubtful terms); re-audited in Phase C of this pass. |
| A11 | `family_relation` over-redacts generic words | **Mitigated this pass (Phase C):** over-redaction measured and reduced. |
| A12 | Version drift (README `0.1.0` vs `v1.0`) | **Resolved** `86e1663`: single version `0.2.0` from `src.__version__`. |
| A13 | CI gaps | **Resolved** `86e1663` + `cd095c7`: matrix 3.9–3.12, `ruff`, coverage ≥85 %, `pip-audit` without `continue-on-error`. |
| A14 | Placeholder map not reset per conversation | **Resolved** (phase 5): in-memory map with per-conversation reset. |
| A15 | Secrets in plaintext `.env` on the client | **Documented** in `docs/threat-model.md` (client secret-at-rest boundary). |
| C1–C8 | Model, corpus and config decisions | **Resolved** (original audit "Resolved" block): repo `BSC-NLP4BIA/bsc-bio-ehr-es-carmen-anon`, revision `83db1112c37c7ef527a9ba6d6b4d1be18b4bca9b`; corpora under `data/` (never pushed); CARMEN-I demoted due to train overlap. |

---

## 2. New findings from this pass

### N1. The leakage history contains spurious readings (commit-by-commit reading)

The history of `eval/results/meddocan.json` (leakage 100 % → 70 % → 18.2 % →
28.4 %) is not a sequence of tuning. Read commit by commit:

- `f9553d3` → `30fb7e2`: the first run **did not process the regexes** (harness
  bug); fixed. **Not a detector change.**
- `8754c1b`: the EMAIL/URL rules **were not running** (preexisting bug, found
  without looking at `dev` or `test`); fixed. **Not a detector change.** In the
  same commit the leakage definition was **narrowed from 7 to 4 classes**
  (`EMAIL, FAMILY, NAME, ID, PHONE, URL, PROFESSIONAL` → `EMAIL, NAME, PHONE,
  ID`). This **was** done with results in view; it is neutralized by always
  reporting **both definitions** (see `eval/PROTOCOL.md`).
- `4f0a3d6`: merge of `NOMBRE_PERSONAL_SANITARIO` and
  `NOMBRE_SUJETO_ASISTENCIA` (and `DOCTOR`) into `NAME`. It is a reasonable
  taxonomy decision (for pseudonymisation any person name gets the same
  treatment), but it was committed **with results in view**; it is justified in
  writing in `eval/PROTOCOL.md` **before** the final run.

Lesson: no metric-definition change may be made with results in view. The
evaluation protocol (`eval/PROTOCOL.md`) freezes definitions and splits before
measuring.

### N2. `code_revision` inconsistent with the code that produced the JSONs

`eval/results/meddocan.json` declares `code_revision: 8754c1b9…`, but it was
produced by later code. No results JSON allows reconstructing which code
produced it. New rule (in `eval/PROTOCOL.md`): every JSON carries
`code_revision` = `git rev-parse HEAD` **at execution time**, and a test marks
`"dirty": true` if the tree was not clean (`git status --porcelain`).

### N3. ID/PHONE confusion in the detector

On `dev`, the ID class has F1 ≈ 0 with high support (1499) and PHONE has
precision ≈ 2 % with high recall. The phone regex
(`\b(?:(?:\+|00)\d{1,3}[\s.-]?)?[3456789](?:[\s.-]?\d){8}\b`) absorbs
identifiers (NHC, DNI, CIP, licence number) that start with a digit and have ≥ 9
digits. Confirmed by the gold→pred confusion matrix in Phase C
(`docs/dev/eval-diagnosis.md`). Fixed in Phase C: phone regex bounded to phone
formats and identifier regexes with concrete formats (DNI/NIE with valid letter,
NHC, CIP, SS), with the most specific rule winning the overlap dedup.

### N4. Fragile placeholder restoration

`deanonymize` used exact `str.replace` and the robustness table in
`eval/results/utility.json` was at 0 % for every perturbation. Fixed in Phase D
with case-insensitive, perturbation-tolerant regex restoration plus a property
test (Hypothesis).

### N5. Unjustified exclusion of Presidio as baseline

The first pass excluded Microsoft Presidio arguing it was "not aligned with the
MEDDOCAN guidelines and performed poorly on CARMEN-I". Neither reason holds: a
poor baseline is still the baseline; taxonomy misalignment is solved by mapping
to the unified set; and neutralization and leakage do not depend on the label.
The standalone Presidio baseline is referenced from `ramsestein/presidio_carmen`
(not re-run here); Presidio is also available as an optional detector component
(`PUKARA_ENABLE_PRESIDIO=1`).

### N6. `docs/dev/` deleted

The `docs/dev/` folder was deleted after the first pass. This pass rewrites it
from the current state (does not restore it): the links from `README.md`,
`docs/SECURITY.md`, `docs/threat-model.md`, `eval/README.md`, `src/secure.py`
and `eval/common.py` resolve again (verified with `grep -rn "docs/dev"`).

---

## 3. Consolidated status by component

- **Protocol v2** (`src/secure.py`): PSK + HKDF-SHA256, direction-separated
  keys, canonical AAD, server-clock freshness, fail-closed anti-replay, response
  bound to `req_id`. ADR: `docs/dev/adr-001-protocol.md`.
- **Proxy** (`src/proxy.py`): `(method, path)` allowlist, body limit, timeouts,
  bounded caches, fail-closed startup, log with `req_id`/reason/size.
- **Detector** (`src/anonymizer.py`): BERT + regex with unified taxonomy;
  fixed in Phase C and frozen in tag `eval-frozen-v2` (Phase D touched
  `src/anonymizer.py`, superseding `eval-frozen-v1`).
- **Restoration** (`deanonymize`): rewritten in Phase D.
- **Evaluation** (`eval/`): protocol frozen in `eval/PROTOCOL.md`; results
  versioned under `eval/results/*.json`.

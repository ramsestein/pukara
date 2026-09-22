# Handoff

## First pass (historical summary)

Branches per phase, all with green tests:

| Phase | Branch | Head |
|---|---|---|
| 0 | `main` | `53c3aea` |
| 1 | `fase1-protocolo-v2` | `606ccec` |
| 2 | `fase2-proxy` | `84ccf5e` |
| 3 | `fase3-threat-model` | `e10da36` |
| 4 | `fase4-evaluacion` | `f9553d3` |
| 5 | `fase5-empaquetado` | `8d33dd9` |

What was done: protocol v2, proxy hardening, whitelist pruning, threat model,
evaluation harness (`eval/`) and SoftwareX packaging. Details in
`docs/dev/audit.md`.

## Second pass

### Detector changes (with `dev` evidence)

- **ID/PHONE confusion**: the phone regex is now bounded to Spanish formats
  (9 digits starting 6/8/9, optional `+34`/`0034`); identifiers have concrete
  formats (DNI/NIE with valid letter, labelled NHC, `XX XX NNNNN`,
  `XX-NNNNNNNN-XX`, CIP, SS, plain 6–10 digits); the most-specific rule wins the
  overlap dedup; and a BERT/regex disagreement rule makes regex win on the
  deterministic classes (`EMAIL, URL, ID, DATE, TIME, PHONE`). Evidence: on dev,
  ID F1 0.00 → 0.22 (support 745); EMAIL F1 0.00 → 0.99 (regex now wins over
  BERT's email fragments). See `docs/dev/eval-diagnosis.md`.
- **NAME recall**: signature triggers ("Remitido por", "Emitido por", "Fdo")
  and `name_single` on name lines; dev NAME false negatives 85 → 8.
- **Whitelist**: removed `ANA` (a given name). No other surnames/toponyms found.
- **Over-redaction**: hospital regex now requires a case-sensitive proper noun,
  adds `Complejo Hospitalario`/`Centro de Salud`, drops `H.`; 2.3 % → 1.7 %.
- **Presidio**: optional third component (`PUKARA_ENABLE_PRESIDIO=1`), off by
  default; adds NAME/EMAIL/LOCATION gap-filling. The standalone baseline is
  **re-run with the same evaluator** (`presidio_meddocan.json`,
  `presidio_carmen.json`, third pass) and, since the fourth pass, also
  configured for Spanish (`presidio_es_*`). The external
  `ramsestein/presidio_carmen` is cited only as origin, not re-run.
- **Phase D**: tolerant placeholder restoration (case-insensitive regex) and a
  BERT noise filter (drops 1-char fragments and pure numbers < 5 digits).

### Before / after

Harness bugs fixed (not detector changes): the first run did not process the
regexes (`f9553d3` → `30fb7e2`) and the EMAIL/URL rules did not run (`8754c1b`).

MEDDOCAN test (single run, frozen `eval-frozen-v2`, revision `b69ddd6`):

- Word F1 0.8443; span relaxed F1 0.8357; span strict F1 0.5923.
- PHI neutralization 0.8859 (CI 0.882–0.900).
- Leakage wide 0.112 (CI 0.072–0.152); direct 0.072 (CI 0.044–0.104).

The first-pass headline (direct leakage 28.4 %) mixed `dev`+`test` and predates
the harness fixes, so it is not directly comparable. The comparable dev ablation
is in `eval/results/ablate_dev_*.json` (combined: word F1 0.8548, relaxed F1
0.7997, wide leakage 0.104).

### Manuscript claims and their backing JSON

| Claim | Backed by |
|---|---|
| Detector reduces direct-identifier leakage on out-of-distribution MEDDOCAN test | `eval/results/meddocan.json` (`leakage.direct`) |
| Wide leakage definition is also reported | `eval/results/meddocan.json` (`leakage.wide`) |
| PHI neutralization (label-agnostic) | `eval/results/meddocan.json` (`phi_neutralization`) |
| Restoration robustness / round-trip | `eval/results/utility.json` |
| Synthetic prompt benchmark dev vs held-out | `eval/results/promptbench.json`, `promptbench_heldout.json` |
| CARMEN-I in-distribution upper bound | `eval/results/carmen_pukara.json` |
| Latency / memory | `eval/results/cost.json` |

Claims that can no longer be sustained: CARMEN-I as a headline result (it is
in-distribution); any leakage figure narrower than the two definitions (7-class
wide and 4-class direct).

### Future work (prioritized by leakage impact)

1. `ORGANIZATION` (F1 < 10 %, no dedicated regex rule).
2. `PHONE` precision (BERT labels many non-phone spans as PHONE).
3. Presidio integration for higher neutralization when the input is not
   pre-pseudonymised.
4. HPKE/Noise-NK for forward secrecy (protocol, not leakage).

### MEDDOCAN test single run

- Executed once: 2026-09-20, revision `b69ddd6eb202`, tag `eval-frozen-v2`,
  tree clean (`git status --porcelain` empty). No `dirty` flag was set.

## Third pass

Executed on `main` from `c6e4ee4`, Spanish commits. The detector is untouched:
`git diff eval-frozen-v2 HEAD -- src/anonymizer.py lista_blanca.txt
src/presidio.py` is empty except the escape/restoration part of
`src/anonymizer.py` (which does not affect detection and is covered by
`tests/test_restore.py`).

### What was run, with which hash

| Artifact | Command | `code_revision` |
|---|---|---|
| `presidio_meddocan.json` | `eval.meddocan --split test --mode presidio` | `31ccec3` |
| `presidio_carmen.json` | `eval.carmen --mode presidio` | `31ccec3` |
| `over_redaction_test.json` | `eval.over_redaction --split test --mode combined` | `edc8968` |
| `over_redaction_test_presidio.json` | `eval.over_redaction --split test --mode presidio` | `edc8968` |
| `over_redaction_dev.json` | `eval.over_redaction --split dev --mode combined --breakdown` | `be0e1d0` |
| `utility.json` | `eval.utility --mode combined` | `c37c16f` |

`meddocan.json` (Pukara test) was **not** re-run in the third pass: at that
point it carried `"dirty": false` added from the tree state at `b69ddd6` (clean,
verified by commit). In the fourth pass it **was** re-run once with the frozen
detector to capture per-document TP/FP/FN and recalculate the CIs with the
ratio estimator; all point values stayed identical to `b69ddd6` (see "Fourth
pass"). The other pre-existing JSONs (`carmen_pukara.json`, `ablate_dev_*`,
`diagnosis.json`, `promptbench*.json`, `cost.json`) received `"dirty": false`
manually in the third pass; `carmen_pukara.json` and `ablate_dev_*` were
regenerated in the fourth pass with the frozen detector (the ablations had been
produced at `b468f31`, pre-freeze).

### Rule 2: test predictions were not saved

The frozen Pukara test run persisted only aggregates (`meddocan.json`, revision
`b69ddd6`); no per-document predictions were saved. The over-redaction rate on
test for Pukara was therefore computed by **re-running the frozen detector**
(identical to `eval-frozen-v2`) on test. This is a re-execution with **no code
changes**, recorded with hash `edc8968` and date 2026-09-20. The Presidio
standalone run (`presidio_meddocan.json`) is a first run with this evaluator,
allowed by rule 2.

### Manuscript claims and their backing JSON

| Claim | Backed by |
|---|---|
| Pukara vs Presidio standalone baseline on MEDDOCAN test (same evaluator) | `meddocan.json`, `presidio_meddocan.json` (tables in `docs/metrics.md`) |
| Presidio standalone on CARMEN-I (same evaluator) | `presidio_carmen.json`; the external `ramsestein/presidio_carmen` is cited only as origin (`es_core_news_md`, 1,000 docs, character Jaccard, not comparable) |
| Over-redaction rate (non-PHI tokens altered) on test | `over_redaction_test.json` (Pukara), `over_redaction_test_presidio.json` (Presidio) |
| Over-redaction per-component breakdown and top-30 false positives | `over_redaction_dev.json` (dev, diagnostic) → `docs/dev/eval-diagnosis.md` §9 |
| Round-trip exact 57/57 with literal-placeholder escape | `utility.json` (`roundtrip`) |
| Spurious restorations n ≥ 500 | `utility.json` (`spurious_restorations`) |

### Figures that changed vs the previous pass

- `utility.json` was regenerated with the frozen `eval-frozen-v2` detector plus
  the escape: round-trip is now 0/57 failures, `lost_brackets` 57.4 % (31/54)
  and `single_bracket` 88.9 % (48/54). The previously recorded 60.7 % / 89.3 %
  came from `eval-frozen-v1` (`f5f59f4`).
- Presidio standalone document-level leakage is 100 % on MEDDOCAN test: the
  leakage definitions include classes (FAMILY, PROFESSIONAL, …) that Presidio
  does not map in `PRESIDIO_TO_UNIFIED`, and every document misses at least one
  direct identifier. It is a baseline, not a candidate configuration.

### Future work

1. `ORGANIZATION` (F1 < 10 %, no dedicated regex rule).
2. `PHONE` precision (BERT labels many non-phone spans as PHONE).
3. Presidio integration for higher neutralization when the input is not
   pre-pseudonymised.
4. HPKE/Noise-NK for forward secrecy (protocol, not leakage).

## Fourth pass

Executed on `main` from `4778b0e`, Spanish commits. Detector untouched:
`git diff eval-frozen-v2 HEAD -- src/anonymizer.py` is limited to restoration/
escape (`deanonymize`, `_restore_placeholder`, `_escape_*`, `_unescape_*`,
`reset.original_tokens`, `__init__.restore_mode`); verified by
`tests/test_frozen_detector.py`.

### What was run, with which hash

| Artifact | `code_revision` | Note |
|---|---|---|
| `meddocan.json` (Pukara test) | `33f22a2` | documented re-execution (frozen detector) |
| `presidio_meddocan.json` / `presidio_es_meddocan.json` | `338431b` / `484f747` | OOTB / ES-configured baseline |
| `presidio_carmen.json` / `presidio_es_carmen.json` | `91f1e27` / `42fae86` | same |
| `over_redaction_test*.json` / `over_redaction_dev.json` | `e1d7fc4` … `9909a54` | ratio CI + per-doc |
| `carmen_pukara.json` | `0a21274` | ratio CI + per-doc |
| `ablate_dev_*.json` | `967c5f4` … `83094a6` | re-executed with frozen detector |
| `utility.json` | `757b7f7` | strict/lenient robustness + spurious |

### `meddocan.json` (Pukara test) re-execution — verification

`b69ddd6` saved only aggregates (no per-document TP/FP/FN, no predicted spans),
and the third-pass over-redaction re-execution (`edc8968`) saved only aggregate
rates. Therefore bit-identity could only be verified at the **aggregate-metric**
level, not span by span. The re-execution with the frozen detector reproduced
every point value byte-for-byte (the only diff vs `b69ddd6` is the added
metadata `presidio_meta: null`; `generated`/`code_revision`/`dirty`/`per_doc`
are the expected additions). Since the metrics are deterministic functions of
the predicted spans, identical aggregates imply identical spans. `per_doc`
(TP/FP/FN and numerator/denominator per document) is now stored so no CI ever
requires re-execution again.

### Fase 2 diff (points changed vs previous commit)

- `meddocan.json` (Pukara test): **no point value changed** (see above).
- `ablate_dev_*.json`: the points **changed** because those files were generated
  at `b468f31` (pre-freeze, Fase B/C) and the frozen detector (`eval-frozen-v2`,
  Fase D) added the BERT noise filter. New dev ablation (frozen): regex word F1
  0.7080, bert 0.8130, combined 0.8444, combined+Presidio 0.8087.
- Everything else (Presidio, CARMEN, over-redaction, utility): points unchanged
  where the detector is the same; `utility.json` changed by design (strict
  default + per-mode measurement).

### Manuscript claims and their backing JSON (fourth pass)

| Claim | Backed by |
|---|---|
| Pukara vs Presidio OOTB vs Presidio ES on MEDDOCAN test (same evaluator, 3 columns) | `meddocan.json`, `presidio_meddocan.json`, `presidio_es_meddocan.json` |
| Same 3-column comparison on CARMEN-I | `carmen_pukara.json`, `presidio_carmen.json`, `presidio_es_carmen.json` |
| Which class causes wide leakage, per system | `leakage.wide.attribution` in each of the three MEDDOCAN JSONs |
| Over-redaction on test for the three systems | `over_redaction_test*.json`; per-component on dev in `over_redaction_dev.json` |
| CIs consistent with the estimator (ratio vs mean) | `tests/test_ci_coverage.py`; §3.7 of `PROTOCOL.md` |
| `strict` restoration by default, `lenient` trade-off | `utility.json` (`robustness`, `spurious_restorations` per mode) |
| Detection frozen | `tests/test_frozen_detector.py` |

### Restoration policy (fourth pass)

`PUKARA_RESTORE_MODE` selects the restoration policy: `strict` (default)
requires both brackets; `lenient` also recovers `single_bracket`/`lost_brackets`
at word boundaries and never over a token already present in the original
prompt. Spurious restorations (placeholder-free texts altered): `strict` 0 %
on both natural and adversarial samples; `lenient` 0 % natural / 100 %
adversarial (31.8 % of characters). `lenient` `lost_brackets` recovery is
16.7 % because the word-boundary safeguard leaves placeholders glued to the
next word unrecovered (BERT fragments like `"H.\n"`, `"\nNAS"`); forcing them
would risk spurious restorations.


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
  referenced from `ramsestein/presidio_carmen` (not re-run).
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


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

Filled in at **Phase H** of the second pass. It contains:

- What changed in the detector and with what `dev` evidence.
- Before/after comparison on `dev` and `test`, distinguishing what part of the
  change comes from fixed harness bugs and what part from detector changes.
- Which manuscript claims are backed by which JSON, and which claims can no
  longer be sustained.
- Future work prioritized by leakage impact.
- Explicit confirmation that `MEDDOCAN/test` ran exactly once, with hash and
  date.

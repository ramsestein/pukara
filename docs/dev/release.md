# Release procedure — v0.2.0 (prepared, NOT executed)

This procedure is documented but **not run** in this pass. Run it only after the
third evaluation pass is merged and `docs/dev/handoff.md` leaves no open
questions.

## 0. Required prior state

- `make eval` regenerates `docs/metrics.md` from `eval/results/*.json`; **no
  README figure comes from any other source**.
- Every JSON under `eval/results/` carries `code_revision`, `generated` and
  `"dirty": false`. `meddocan.json` (Pukara test) is frozen and never re-run.
- The detector is frozen in tag `eval-frozen-v2` (or later) and `MEDDOCAN/test`
  ran exactly once for Pukara (see `docs/dev/handoff.md`).

## 1. Pre-release checks

```bash
python -m pytest -q \
  --cov=src.secure --cov=src.proxy --cov-fail-under=85 --cov-report=term-missing
ruff check src tests eval
pip-audit -r requirements.txt
```

## 2. Tag and release

```bash
git checkout main
git tag -a v0.2.0 -m "Pukara v0.2.0"
git push origin v0.2.0
```

`pyproject.toml` reads the version from `src.__version__` (single source of
truth), currently `0.2.0`.

## 3. Zenodo

- The repository must be linked to a Zenodo record (GitHub ↔ Zenodo
  integration).
- `CITATION.cff` (root) and `.zenodo.json` (root) carry `TODO` markers for
  ORCIDs and the SoftwareX DOI; fill them before archiving.
- Draft a new version in Zenodo for tag `v0.2.0`, verify the metadata (authors,
  MIT license, version 0.2.0) and publish. The DOI is then added to the README
  metadata table (currently "Pending").

## 4. Final checklist (fourth pass, not executed)

- [x] `LICENSE` and `CITATION.cff` at the repository root.
- [x] `"dirty": false` in every `eval/results/*.json`.
- [x] CI-equivalent checks green locally: `ruff check src tests eval`, `pytest`
      (93 tests, coverage 91.5 % on `secure.py`/`proxy.py`), `pip-audit`.
- [x] Detector frozen: `tests/test_frozen_detector.py` and
      `git diff eval-frozen-v2 HEAD -- src/anonymizer.py` limited to
      restoration/escape.
- [x] Three-column comparison (Pukara / Presidio OOTB / Presidio ES) and
      leakage attribution in `docs/metrics.md`.
- [ ] Run `make eval` on a clean tree and commit any regenerated artifacts; the
      frozen test JSONs are not touched by `make eval`.
- [ ] CI green on GitHub across the full matrix (3.9–3.12 + Docker build).
- [ ] Tag `v0.2.0` and publish the GitHub release.
- [ ] Archive in Zenodo (new version for `v0.2.0`), obtain the DOI.
- [ ] Add the DOI to `README.md`, `CITATION.cff` and `.zenodo.json`.
- [ ] From here on, `eval/results/` is frozen (no regeneration).

The tag, the Zenodo archive and the DOI are done **by the author by hand** when
the release is approved.

## 5. SoftwareX submission

- The DOI from step 3 goes into the SoftwareX manuscript metadata.
- `docs/dev/handoff.md` lists which manuscript claims are backed by which
  `eval/results/*.json` (sections "Second pass", "Third pass" and "Fourth pass").

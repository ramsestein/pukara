# Release procedure — v0.2.0 (prepared, NOT executed)

This procedure is documented but **not run** in this pass. It should only be run
once the evaluation phases are complete and `docs/dev/handoff.md` leaves no open
questions.

## 0. Required prior state

- `make eval` regenerates `docs/metrics.md` from `eval/results/*.json`; **no
  README figure comes from any other source**.
- The tree is clean (`git status --porcelain` empty) and every JSON under
  `eval/results/` carries `code_revision` equal to the commit that produced it
  and `"dirty": false`.
- The detector is frozen in tag `eval-frozen-v2` (or later) and `MEDDOCAN/test`
  ran exactly once (see `docs/dev/handoff.md`).

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
- `docs/CITATION.cff` and `docs/.zenodo.json` carry `TODO` markers for ORCIDs and the
  SoftwareX DOI; fill them before archiving.
- Draft a new version in Zenodo for tag `v0.2.0`, verify the metadata (authors,
  MIT license, version 0.2.0) and publish. The DOI is then added to the README
  metadata table (currently "Pending").

## 4. SoftwareX submission

- The DOI from step 3 goes into the SoftwareX manuscript metadata.
- `docs/dev/handoff.md` lists which manuscript claims are backed by which
  `eval/results/*.json` (section "Second pass").

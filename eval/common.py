"""Shared utilities for the Pukara evaluation harness (Phase 4).

Run scripts from the repository root with `python -m eval.<script>`. This module
bootstraps `sys.path` so `src` and `eval` are importable from any working
directory.
"""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import anonymizer  # noqa: E402

# Direct identifiers. These, and only these, are the identifiers whose
# leakage is the security-critical figure: EMAIL, NAME, PHONE, ID.
CRITICAL_TAGS = {"EMAIL", "NAME", "PHONE", "ID"}

# Definición amplia de leakage (principal, PROTOCOL.md): las 7 clases de la
# primera versión.
WIDE_TAGS = {"EMAIL", "FAMILY", "NAME", "ID", "PHONE", "URL", "PROFESSIONAL"}

# Pinned model identity used for every BERT-based evaluation.
MODEL_META = {
    "repo": "BSC-NLP4BIA/bsc-bio-ehr-es-carmen-anon",
    "revision": "83db1112c37c7ef527a9ba6d6b4d1be18b4bca9b",
    # SHA-256 of the local pytorch_model.bin (see docs/dev/handoff.md).
    "weights_sha256": "a8b2976c284b72db42adf97df8d5a1609ca477f3abdae71a5d201d4d3ff89acd",
}


# ── Parsing ────────────────────────────────────────────────────────────────
def read_text(txt_path: Path) -> str:
    return txt_path.read_text(encoding="utf-8")


def parse_brat(ann_path: Path) -> list[dict]:
    """Parse a brat `.ann` file into `[{"start","end","label","text"}]`.

    Discontinuous (multi-fragment) annotations are reduced to their enclosing
    span, which is a conservative upper bound for leakage.
    """
    entities = []
    for line in ann_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("T"):
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        head = fields[1].split()
        if len(head) < 3:
            continue
        label = head[0]
        start = int(head[1])
        end = int(head[-1])
        entities.append(
            {"start": start, "end": end, "label": label, "text": fields[2]}
        )
    return entities


def map_gold_label(label: str) -> str:
    """Map a MEDDOCAN/CARMEN brat label to the unified taxonomy."""
    return anonymizer.BRAT_TO_UNIFIED.get(label, "OTHER")


def gold_to_unified(gold: list[dict]) -> list[dict]:
    out = []
    for g in gold:
        out.append(
            {
                "start": g["start"],
                "end": g["end"],
                "label": map_gold_label(g["label"]),
                "text": g["text"],
            }
        )
    return out


def regex_only_detect(text: str) -> list[dict]:
    """Run the regex-only detector without loading the BERT model.

    `Anonymizer.__new__` skips `__init__` (which loads torch/transformers); the
    regex detector only reads module-level constants, so this is safe and fast.
    """
    anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
    return anon._regex_detect(text)


class Predictor:
    """Unified detector/anonymizer for the eval harness.

    `mode` is one of "regex", "bert", "combined" or "presidio".
    "combined" runs BERT+regex (+ Presidio when `use_presidio=True`, default).
    "presidio" is the standalone baseline (all Presidio entities, no BERT).
    """

    def __init__(self, mode: str, model_dir=None, use_presidio=False):
        self.mode = mode
        if mode == "regex":
            self._anon = anonymizer.Anonymizer.__new__(anonymizer.Anonymizer)
            self._anon.reset()
            self._anon.detect = self._anon._regex_detect
        elif mode == "presidio":
            self._anon = None
        else:
            from src import anonymizer as _an

            # Anonymizer expects the PARENT directory (it appends the repo
            # basename), i.e. the `models/` folder.
            model_dir = model_dir or (ROOT / "models")
            self._anon = _an.Anonymizer(model_dir=model_dir, use_presidio=use_presidio)

    def detect(self, text: str) -> list[dict]:
        if self.mode == "presidio":
            from src import presidio
            return presidio.detect_full(text)
        if self.mode == "bert":
            return self._anon._bert_detect(text)
        return self._anon.detect(text)

    def anonymize(self, text: str):
        """Return (anonymized_text, text_to_ph map)."""
        self._anon.reset()
        return self._anon.anonymize(text), self._anon.text_to_ph

    def deanonymize(self, text: str) -> str:
        return self._anon.deanonymize(text)


# ── Span matching ──────────────────────────────────────────────────────────
def _span_exact(a: dict, b: dict) -> bool:
    return a["start"] == b["start"] and a["end"] == b["end"]


def _span_overlap(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def span_prf(gold: list[dict], pred: list[dict], strict: bool) -> tuple:
    """Binary PHI span-level P/R/F1. Returns (p, r, f1)."""
    matched_gold = set()
    matched_pred = set()
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            if pi in matched_pred:
                continue
            if (_span_exact(g, p) if strict else _span_overlap(g, p)):
                matched_gold.add(gi)
                matched_pred.add(pi)
                break
    tp = len(matched_gold)
    fp = len(pred) - len(matched_pred)
    fn = len(gold) - len(matched_gold)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def per_class_prf(gold: list[dict], pred: list[dict]) -> dict:
    """Strict span+label evaluation per unified label."""
    labels = sorted({g["label"] for g in gold} | {p["label"] for p in pred})
    out = {}
    for lab in labels:
        g = [x for x in gold if x["label"] == lab]
        p = [x for x in pred if x["label"] == lab]
        tp = 0
        matched = set()
        for gg in g:
            for pi, pp in enumerate(p):
                if pi in matched:
                    continue
                if _span_exact(gg, pp):
                    tp += 1
                    matched.add(pi)
                    break
        fp = len(p) - len(matched)
        fn = len(g) - tp
        out[lab] = {
            "precision": tp / (tp + fp) if (tp + fp) else 0.0,
            "recall": tp / (tp + fn) if (tp + fn) else 0.0,
            "f1": (2 * tp) / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0,
            "support": len(g),
        }
    return out


def word_prf(text: str, gold: list[dict], pred: list[dict]) -> tuple:
    """Binary PHI word-level P/R/F1 over whitespace tokens."""
    tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    gold_tok = {i for i, (s, e) in enumerate(tokens)
                if any(s < g["end"] and g["start"] < e for g in gold)}
    pred_tok = {i for i, (s, e) in enumerate(tokens)
                if any(s < p["end"] and p["start"] < e for p in pred)}
    tp = len(gold_tok & pred_tok)
    fp = len(pred_tok - gold_tok)
    fn = len(gold_tok - pred_tok)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def _document_leakage_for(gold: list[dict], pred: list[dict], tags: set) -> bool:
    """True if a gold span of any of `tags` has no overlapping prediction."""
    return any(
        g["label"] in tags and not any(_span_overlap(g, p) for p in pred)
        for g in gold
    )


def document_leakage(gold: list[dict], pred: list[dict]) -> bool:
    """True if a document has at least one missed direct identifier
    (EMAIL, NAME, PHONE, ID)."""
    return _document_leakage_for(gold, pred, CRITICAL_TAGS)


def document_leakage_wide(gold: list[dict], pred: list[dict]) -> bool:
    """True if a document misses a span of the wide definition (7 clases)."""
    return _document_leakage_for(gold, pred, WIDE_TAGS)


def document_leakage_any(gold: list[dict], pred: list[dict]) -> bool:
    """True if a document has any gold PHI span missed, regardless of label.

    This is the label-agnostic leakage: what matters for anonymization is not
    whether the predicted label is right, but whether the real PHI text is
    replaced at all before it leaves the client.
    """
    return any(not any(_span_overlap(g, p) for p in pred) for g in gold)


def span_coverage(gold: list[dict], pred: list[dict]) -> tuple:
    """Return (covered, total) gold spans with >=1 overlapping prediction.

    Label-agnostic: a PHI span is "neutralized" if any predicted span overlaps
    it, even if the predicted label is wrong.
    """
    covered = 0
    for g in gold:
        if any(_span_overlap(g, p) for p in pred):
            covered += 1
    return covered, len(gold)


# ── Bootstrap ──────────────────────────────────────────────────────────────
def bootstrap_ci(values: list, n: int = 1000, seed: int = 42) -> tuple:
    """95% percentile bootstrap CI of the mean of `values`."""
    rng = random.Random(seed)
    size = len(values)
    if size == 0:
        return (0.0, 0.0)
    means = []
    for _ in range(n):
        sample = [values[rng.randrange(size)] for _ in range(size)]
        means.append(sum(sample) / size)
    means.sort()
    return means[int(0.025 * (n - 1))], means[int(0.975 * (n - 1))]

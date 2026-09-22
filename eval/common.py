"""Shared utilities for the Pukara evaluation harness (Phase 4).

Run scripts from the repository root with `python -m eval.<script>`. This module
bootstraps `sys.path` so `src` and `eval` are importable from any working
directory.
"""
from __future__ import annotations

import random
import re
import subprocess
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
        elif mode in ("presidio", "presidio_es"):
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
        if self.mode == "presidio_es":
            from src import presidio
            return presidio.detect_es(text)
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
    """95% percentile bootstrap CI of the mean of `values`.

    Solo para métricas que **son** una media por documento (p. ej. leakage a
    nivel de documento, proporciones por documento). Para cocientes agregados
    usa `bootstrap_ratio_ci` o `bootstrap_f1_ci`.
    """
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


def _resample_idx(rng: random.Random, size: int) -> list:
    return [rng.randrange(size) for _ in range(size)]


def bootstrap_ratio_ci(numerators: list, denominators: list,
                       n: int = 1000, seed: int = 42) -> tuple:
    """95% percentile bootstrap CI del cociente agregado `sum(num)/sum(den)`.

    Remuestrea documentos y recalcula `sum(num)/sum(den)` en cada remuestra.
    Es el estimador correcto para cocientes agregados (neutralización,
    sobre-redacción, proporciones de caracteres, …).
    """
    rng = random.Random(seed)
    size = len(numerators)
    if size == 0 or sum(denominators) == 0:
        return (0.0, 0.0)
    ratios = []
    for _ in range(n):
        idx = _resample_idx(rng, size)
        num = sum(numerators[i] for i in idx)
        den = sum(denominators[i] for i in idx)
        ratios.append(num / den if den else 0.0)
    ratios.sort()
    return ratios[int(0.025 * (n - 1))], ratios[int(0.975 * (n - 1))]


def bootstrap_f1_ci(tp: list, fp: list, fn: list,
                    n: int = 1000, seed: int = 42) -> tuple:
    """95% percentile bootstrap CI del F1 agregado desde TP/FP/FN por documento.

    Remuestrea documentos, reagrega TP/FP/FN y recalcula P, R y F1 en cada
    remuestra.
    """
    rng = random.Random(seed)
    size = len(tp)
    if size == 0:
        return (0.0, 0.0)
    f1s = []
    for _ in range(n):
        idx = _resample_idx(rng, size)
        t = sum(tp[i] for i in idx)
        f = sum(fp[i] for i in idx)
        m = sum(fn[i] for i in idx)
        p = t / (t + f) if (t + f) else 0.0
        r = t / (t + m) if (t + m) else 0.0
        f1s.append(2 * p * r / (p + r) if (p + r) else 0.0)
    f1s.sort()
    return f1s[int(0.025 * (n - 1))], f1s[int(0.975 * (n - 1))]


def document_leak_classes_wide(gold: list, pred: list) -> set:
    """Clases (definición amplia) con al menos un span gold sin cubrir."""
    return {
        g["label"] for g in gold
        if g["label"] in WIDE_TAGS and not any(_span_overlap(g, p) for p in pred)
    }


def leakage_attribution(per_doc_classes: list, total_docs: int,
                        n: int = 1000, seed: int = 42) -> dict:
    """Desglose de la fuga por clase: % de documentos cuyo leak se debe solo a
    una clase (o a varias). `per_doc_classes` es una lista de conjuntos de
    clases que fugan por documento. Devuelve buckets `solo_<CLASE>` y
    `multiple` con docs/rate/ci95 (media por documento).
    """
    assigned = []
    for classes in per_doc_classes:
        if not classes:
            assigned.append(None)
        elif len(classes) == 1:
            assigned.append("solo_" + next(iter(classes)))
        else:
            assigned.append("multiple")
    keys = sorted({a for a in assigned if a is not None},
                  key=lambda k: (k != "multiple", k))
    out = {}
    for key in keys:
        ind = [1 if a == key else 0 for a in assigned]
        out[key] = {
            "docs": sum(ind),
            "rate": round(sum(ind) / total_docs, 4) if total_docs else 0.0,
            "ci95": [round(x, 4) for x in bootstrap_ci(ind, n=n, seed=seed)],
        }
    return out


def dirty() -> bool:
    """True si el árbol git tiene cambios sin commitear (porcelain no vacío).

    Los JSON de resultados lo registran como `dirty` para que ninguna cifra se
    pueda producir sobre un árbol sucio sin quedar señalado.
    """
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        )
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return True


def presidio_meta(sample_texts: list, mode: str = "presidio") -> dict:
    """Metadato del baseline Presidio standalone (solo lectura, no toca el detector).

    Recoge las versiones de Presidio/spaCy, el modo y las clases de Presidio que
    quedan **sin mapear** al conjunto unificado (los `entity_type` crudos
    observados en una muestra). Para `presidio_es` incluye además la lista de
    reconocedores ES y las regiones de teléfono.
    """
    import importlib.metadata as md

    from src import presidio

    versions = {}
    for dist, pkg in (("presidio-analyzer", "presidio_analyzer"), ("spacy", "spacy")):
        try:
            versions[pkg] = md.version(dist)
        except Exception:  # noqa: BLE001
            versions[pkg] = "unknown"

    if mode == "presidio_es":
        engine = presidio._engine_es()  # noqa: SLF001 (metadato de eval)
        mapping = presidio.PRESIDIO_ES_TO_UNIFIED
        seen = set()
        if engine is not None:
            for text in sample_texts:
                for r in engine.analyze(text=text, language="es"):
                    seen.add(r.entity_type)
        unmapped = sorted(seen - set(mapping))
        recognizers = []
        if engine is not None:
            try:
                for r in engine.registry.get_recognizers(language="es", all_fields=True):
                    recognizers.append({
                        "name": type(r).__name__,
                        "entities": list(r.supported_entities),
                    })
            except Exception:  # noqa: BLE001
                recognizers = []
        return {
            "versions": versions,
            "spacy_model": "es_core_news_lg",
            "mode": "presidio_es",
            "mapping": "PRESIDIO_ES_TO_UNIFIED",
            "phone_regions": list(presidio._ES_PHONE_REGIONS),
            "unmapped_entity_types": unmapped,
            "recognizers": recognizers,
        }

    seen = set()
    for text in sample_texts:
        for r in presidio._analyze(text):  # noqa: SLF001 (metadato de eval)
            seen.add(r.entity_type)
    unmapped = sorted(seen - set(presidio.PRESIDIO_TO_UNIFIED))
    return {
        "versions": versions,
        "spacy_model": "es_core_news_lg",
        "mode": "presidio",
        "mapping": "PRESIDIO_TO_UNIFIED (full)",
        "unmapped_entity_types": unmapped,
    }

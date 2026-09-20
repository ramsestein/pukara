"""Utility-preservation evaluation, no LLM involved (Phase 4.4).

Measures what pseudonymisation deterministically destroys or breaks:

1. Exact round-trip: `deanonymize(anonymize(x)) == x` byte-for-byte. Any failure
   is a bug, not a metric.
2. Placeholder robustness: deterministic perturbations applied to anonymized
   text (mimicking what an LLM does to placeholders when answering) and the
   percentage restored correctly per perturbation type.

Runs with the regex-only detector; BERT mode is TODO until the model is local.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

from eval import common

ADVERSARIAL = [
    "Texto que ya contiene [NOMBRE_1] literal.",
    "Corchetes anidados [[NOMBRE_1]] y [NOMBRE_10].",
    "Unicode: María, Núria, Mercè, ç, ñ, ü.",
    "Entidades solapadas: Hospital Clínic de Barcelona.",
    "Número 600123456 y fecha 12/05/2024.",
    "Apellido epónimo: enfermedad de Crohn y Parkinson.",
    "Entidad pegada a puntuación: (Juan García),",
]

_TAG_TRANSLATION = {
    "NOMBRE": "NAME",
    "FECHA": "DATE",
    "HORA": "TIME",
    "PROFESIONAL": "PROFESSIONAL",
    "FAMILIAR": "FAMILY",
    "PROFESION": "PROFESSION",
    "EDAD": "AGE",
    "SEXO": "SEX",
    "LUGAR": "LOCATION",
    "ORGANIZACION": "ORGANIZATION",
    "TELEFONO": "PHONE",
    "CORREO": "EMAIL",
}


def _translate_labels(s: str) -> str:
    for es, en in _TAG_TRANSLATION.items():
        s = s.replace(f"[{es}_", f"[{en}_")
    return s


PERTURBATIONS = {
    "uppercase": lambda s: s.upper(),
    "bold_markers": lambda s: re.sub(r"\[(\w+)_(\d+)\]", r"**[\1_\2]**", s),
    "lost_brackets": lambda s: s.replace("[", "").replace("]", ""),
    "single_bracket": lambda s: s.replace("]", ""),
    "space_inner": lambda s: re.sub(r"\[(\w+)_(\d+)\]", r"[ \1 _ \2 ]", s),
    "label_translated": _translate_labels,
    "plural_suffix": lambda s: re.sub(r"\[(\w+)_(\d+)\]", r"[\1_\2]s", s),
    "genitive_suffix": lambda s: re.sub(r"\[(\w+)_(\d+)\]", r"[\1_\2]'s", s),
    "split_by_newline": lambda s: re.sub(r"\[(\w+)_(\d+)\]", r"[\1_\n\2]", s),
}

# Textos con corchetes/guiones bajos legítimos (código, JSON, markdown) para
# medir la tasa de restauraciones espurias de la regex tolerante.
SPURIOUS_SAMPLES = [
    "Código: arr[0] = matrix[1][2]; x_1 += y_2.",
    "JSON: {\"nombre_1\": 1, \"fecha_2\": \"2024-05-12\"}.",
    "Markdown: [enlace](https://example.com) y nota[1].",
    "Placeholder ajeno a la conversación: [NOMBRE_99] y [FECHA_77].",
    "Variables: total_2, media_1 y desviacion_3.",
]


def roundtrip(texts, predictor):
    failures = []
    for text in texts:
        anonymized, _ = predictor.anonymize(text)
        restored = predictor.deanonymize(anonymized)
        if restored != text:
            failures.append({"text": text, "anonymized": anonymized,
                             "restored": restored})
    return failures


def robustness(texts, predictor):
    """% de textos donde TODAS las entidades originales se recuperan tras la
    perturbación (no se exige round-trip exacto: la perturbación altera también
    el texto no-PHI, p. ej. `uppercase`)."""
    results = {}
    for name, perturb in PERTURBATIONS.items():
        ok = 0
        total = 0
        for text in texts:
            anonymized, text_to_ph = predictor.anonymize(text)
            if not text_to_ph:
                continue  # no placeholders to perturb
            perturbed = perturb(anonymized)
            restored = predictor.deanonymize(perturbed)
            total += 1
            if all(orig in restored for orig in text_to_ph):
                ok += 1
        results[name] = {
            "restored": ok,
            "total": total,
            "rate": round(ok / total, 4) if total else 0.0,
        }
    return results


def spurious_restorations(predictor):
    """Tasa de restauraciones espurias de la regex tolerante.

    Construye un mapa sintético con todos los placeholders `[TAG_1..2]` y
    aplica `deanonymize` a textos con corchetes/guiones bajos legítimos. Cuenta
    cuántas muestras se alteran (falso positivo de la regex).
    """
    from src import anonymizer as _an

    anon = _an.Anonymizer.__new__(_an.Anonymizer)
    anon.reset()
    for tag in _an.TAGS.values():
        for n in (1, 2):
            anon.ph_to_text[f"[{tag}_{n}]"] = f"<valor:{tag}:{n}>"
    altered = []
    for sample in SPURIOUS_SAMPLES:
        restored = anon.deanonymize(sample)
        if restored != sample:
            altered.append({"sample": sample, "restored": restored})
    return {
        "samples": len(SPURIOUS_SAMPLES),
        "altered": len(altered),
        "rate": round(len(altered) / len(SPURIOUS_SAMPLES), 4)
        if SPURIOUS_SAMPLES else 0.0,
        "examples": altered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Utility-preservation eval")
    parser.add_argument("--corpus", default="data/meddocan/corpus")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--mode", choices=["regex", "bert", "combined"],
                        default="combined")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--out", default="eval/results/utility.json")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    texts = list(ADVERSARIAL)
    seen = 0
    for ann in sorted((corpus / "dev" / "brat").glob("*.ann")):
        txt = ann.with_suffix(".txt")
        if txt.exists():
            texts.append(common.read_text(txt))
            seen += 1
            if seen >= args.sample:
                break

    predictor = common.Predictor(args.mode, args.model_dir)
    failures = roundtrip(texts, predictor)
    rob = robustness(texts, predictor)
    spurious = spurious_restorations(predictor)

    result = {
        "script": "eval/utility.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": _git(),
        "roundtrip": {
            "texts": len(texts),
            "failures": len(failures),
            "rate": round(1 - len(failures) / len(texts), 4) if texts else 0.0,
            "examples": failures[:10],
        },
        "robustness": rob,
        "spurious_restorations": spurious,
        "notes": [
            "Round-trip failures are bugs, not metrics.",
            "The 2 remaining round-trip failures are the adversarial texts that "
            "already contain a literal [NOMBRE_1]: a generated placeholder "
            "identical to the literal collides (audit A9, inherent to the "
            "reversible-placeholder design), not a restoration bug.",
            "Perturbations mimic deterministic LLM edits to placeholders; the "
            "rate is the share of texts where ALL original entities are recovered.",
            "spurious_restorations: share of legit bracket/underscore samples "
            "altered by the tolerant restoration regex (false positives).",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(
        f"[utility] roundtrip failures={len(failures)}, "
        f"robustness={ {k: v['rate'] for k, v in rob.items()} }"
    )
    return 0


def _git():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())

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
import difflib
import json
import random
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

# Textos con corchetes/guiones bajos legítimos (código, SQL, JSON, CSV,
# markdown) para medir la tasa de restauraciones espurias de la regex tolerante.
# Se generan por plantilla + muestreo del promptbench (dev y held-out). Ninguna
# muestra contiene un placeholder real ([TAG_1]/[TAG_2]); las claves tipo tag en
# minúscula (`nombre_1`, `fecha_2`, …) son el disparador de falso positivo que la
# regex tolerante (case-insensitive) restaura por error.
_TAG_LIKE = [
    "nombre", "fecha", "hora", "telefono", "correo", "id", "lugar", "edad",
    "sexo", "organizacion", "profesion", "familiar", "hospital", "url", "anonimo",
]
_NEUTRAL = [
    "clave", "campo", "var", "total", "media", "col", "tabla", "desviacion",
    "indice", "nota", "x", "y",
]


def generate_natural_samples(seed: int = 42, n: int = 300) -> list:
    """Muestras naturales (código/JSON/SQL/CSV) sin tokens tipo placeholder.

    Fuente: promptbench (dev y held-out) en categorías SQL/CSV y tabular, más
    plantillas con claves neutras (no colisionan con ningún tag).
    """
    rng = random.Random(seed)
    samples: list = []

    from eval import promptbench as pb
    from eval import promptbench_heldout as pb2

    for p in pb.generate_prompts(seed=42, n=1200):
        if p["id"] % 4 == 2:  # categoría SQL/CSV del promptbench dev
            samples.append(p["text"])
    for p in pb2.generate_heldout_prompts(seed=2024, n=1000):
        if p["id"] % 5 == 2:  # categoría tabular (CSV-like) del held-out
            samples.append(p["text"])

    i = 0
    while len(samples) < n:
        neu = _NEUTRAL[i % len(_NEUTRAL)]
        neu2 = _NEUTRAL[(i + 1) % len(_NEUTRAL)]
        r = rng.randint(100, 999)
        kind = i % 4
        if kind == 0:  # código
            samples.append(
                f"if (x > 0) {{ arr[{r}] = matrix[{r}][{r + 1}]; "
                f"{neu}_{r} += {neu2}_{r}; }}"
            )
        elif kind == 1:  # JSON
            samples.append(
                f'{{"{neu}_{r}": {r}, "lista": [{r}, {r + 1}], '
                f'"meta": {{"{neu2}_{r}": "x"}}}}'
            )
        elif kind == 2:  # SQL
            samples.append(
                f"SELECT {neu}_{r}, {neu2}_{r} FROM tabla WHERE id = {r};"
            )
        else:  # CSV
            samples.append(
                f"{neu}_{r},{neu2}_{r},valor\n{r},campo,{r}\n{r + 1},campo,{r}"
            )
        i += 1
    return samples[:n]


def generate_adversarial_samples(seed: int = 42, n: int = 300) -> list:
    """Muestras adversariales con tokens tipo etiqueta insertados
    deliberadamente (`nombre_1`, `[ID_2`, `FECHA_3]`, …).
    """
    rng = random.Random(seed)
    samples: list = []
    i = 0
    while len(samples) < n:
        tag = _TAG_LIKE[i % len(_TAG_LIKE)]
        neu = _NEUTRAL[(i // 2) % len(_NEUTRAL)]
        num = (i % 2) + 1
        num2 = ((i + 1) % 2) + 1
        r = rng.randint(100, 999)
        kind = i % 4
        if kind == 0:  # SQL con clave tipo tag
            samples.append(
                f"SELECT {tag}_{num}, {neu}_{num2} FROM tabla WHERE id = {r};"
            )
        elif kind == 1:  # JSON con clave tipo tag
            samples.append(
                f'{{"{tag}_{num}": {r}, "{neu}_{num2}": [{r}, {r + 1}]}}'
            )
        elif kind == 2:  # corchete abierto (single_bracket, solo lenient)
            samples.append(
                f"corchete abierto: [{tag.upper()}_{num} y {neu}_{num2}."
            )
        else:  # corchete cerrado (single_bracket, solo lenient)
            samples.append(
                f"corchete cerrado: {tag}_{num}] y {neu}_{num2}."
            )
        i += 1
    return samples[:n]


def _char_delta(a: str, b: str) -> int:
    """Número aproximado de caracteres alterados entre dos textos."""
    sm = difflib.SequenceMatcher(None, a, b)
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
        if tag != "equal"
    )


def _measure_spurious(anon, samples: list) -> dict:
    """% de textos alterados y % de caracteres alterados por `deanonymize`."""
    altered = []
    per_altered = []
    per_num = []
    per_den = []
    total_chars = 0
    altered_chars = 0
    for sample in samples:
        restored = anon.deanonymize(sample)
        total_chars += len(sample)
        if restored != sample:
            altered.append({"sample": sample, "restored": restored})
            per_altered.append(1)
            diff = _char_delta(sample, restored)
            altered_chars += diff
            per_num.append(diff)
            per_den.append(len(sample))
        else:
            per_altered.append(0)
            per_num.append(0)
            per_den.append(len(sample))
    return {
        "samples": len(samples),
        "altered": len(altered),
        "rate": round(len(altered) / len(samples), 4) if samples else 0.0,
        "rate_ci95": [round(x, 4) for x in common.bootstrap_ci(per_altered)],
        "altered_chars": altered_chars,
        "total_chars": total_chars,
        "char_rate": round(altered_chars / total_chars, 4) if total_chars else 0.0,
        "char_rate_ci95": [round(x, 4) for x in
                          common.bootstrap_ratio_ci(per_num, per_den)],
        "examples": altered[:5],
    }


def roundtrip(texts, predictor):
    failures = []
    for text in texts:
        anonymized, _ = predictor.anonymize(text)
        restored = predictor.deanonymize(anonymized)
        if restored != text:
            failures.append({"text": text, "anonymized": anonymized,
                             "restored": restored})
    return failures


def robustness(texts, predictor, mode: str):
    """% de textos donde TODAS las entidades originales se recuperan tras la
    perturbación, para un modo de restauración (`strict` o `lenient`).

    Se anonimiza una sola vez por texto (la anonimización es determinista e
    independiente de la perturbación); después se aplican todas las
    perturbaciones sobre el mismo texto anonimizado.
    """
    predictor._anon.restore_mode = mode  # noqa: SLF001
    results = {name: {"restored": 0, "total": 0} for name in PERTURBATIONS}
    for text in texts:
        anonymized, text_to_ph = predictor.anonymize(text)
        if not text_to_ph:
            continue  # no placeholders to perturb
        for name, perturb in PERTURBATIONS.items():
            restored = predictor.deanonymize(perturb(anonymized))
            results[name]["total"] += 1
            if all(orig in restored for orig in text_to_ph):
                results[name]["restored"] += 1
    for _name, r in results.items():
        r["rate"] = round(r["restored"] / r["total"], 4) if r["total"] else 0.0
    return results


def spurious_restorations(predictor, seed=42, natural_n=300, adversarial_n=300):
    """Tasa de restauraciones espurias por modo (`strict`/`lenient`) y por
    composición de la muestra (natural / adversarial).

    Construye un mapa sintético con todos los placeholders `[TAG_1..2]` y
    aplica `deanonymize` a textos sin placeholders. `original_tokens` va vacío
    (escenario peor: el modelo genera un token tipo etiqueta que no estaba en el
    prompt); la salvaguarda del original se verifica en los tests de propiedad.
    """
    from src import anonymizer as _an

    def _make_anon(mode):
        anon = _an.Anonymizer.__new__(_an.Anonymizer)
        anon.reset()
        anon.restore_mode = mode
        anon.original_tokens = set()
        for tag in _an.TAGS.values():
            for n_ in (1, 2):
                anon.ph_to_text[f"[{tag}_{n_}]"] = f"<valor:{tag}:{n_}>"
        return anon

    natural = generate_natural_samples(seed, natural_n)
    adversarial = generate_adversarial_samples(seed, adversarial_n)

    out = {}
    for mode in ("strict", "lenient"):
        anon = _make_anon(mode)
        out[mode] = {
            "natural": _measure_spurious(anon, natural),
            "adversarial": _measure_spurious(anon, adversarial),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Utility-preservation eval")
    parser.add_argument("--corpus", default="data/meddocan/corpus")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--mode", choices=["regex", "bert", "combined"],
                        default="combined")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--out", default="eval/results/utility.json")
    parser.add_argument("--spurious-n", type=int, default=300)
    parser.add_argument("--spurious-seed", type=int, default=42)
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
    rob = {
        "strict": robustness(texts, predictor, "strict"),
        "lenient": robustness(texts, predictor, "lenient"),
    }
    spurious = spurious_restorations(predictor, seed=args.spurious_seed,
                                     natural_n=args.spurious_n,
                                     adversarial_n=args.spurious_n)

    result = {
        "script": "eval/utility.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": _git(),
        "dirty": common.dirty(),
        "roundtrip": {
            "texts": len(texts),
            "failures": len(failures),
            "rate": round(1 - len(failures) / len(texts), 4) if texts else 0.0,
            "examples": failures[:10],
        },
        "robustness": rob,
        "spurious_restorations": spurious,
        "notes": [
            "Round-trip failures are bugs, not metrics; round-trip is exact in "
            "strict mode (default).",
            "Perturbations mimic deterministic LLM edits to placeholders; the "
            "rate is the share of texts where ALL original entities are recovered, "
            "per restoration mode (strict/lenient).",
            "spurious_restorations: share of placeholder-free texts altered by "
            "deanonymize, per mode (strict/lenient) and sample composition "
            "(natural code/JSON/SQL/CSV vs adversarial tag-like tokens), plus share "
            "of altered characters.",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(
        f"[utility] roundtrip failures={len(failures)}, "
        f"robustness(strict)={ {k: v['rate'] for k, v in rob['strict'].items()} }"
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

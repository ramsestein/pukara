"""Sobre-redacción (over-redaction): tokens no-PHI cubiertos por predicciones.

Métrica agnóstica de dominio: % de tokens que **no** son PHI en gold y que
quedan dentro de un span predicho. Global con IC bootstrap por documento.

- `--split test --mode combined|presidio`: cifra reportable.
- `--split dev --mode combined --breakdown`: desglose diagnóstico por
  componente (regex por etiqueta, BERT, ambos) y los N falsos positivos más
  frecuentes. El desglose se calcula en `dev` porque las predicciones de test
  congeladas no guardan procedencia; `dev` no es reportable.

Las predicciones de test de Pukara no se persistieron en la ejecución congelada
(solo los agregados de `meddocan.json`), así que este script re-ejecuta la
detección con el detector congelado (`eval-frozen-v2`, sin cambios de código);
ver `docs/dev/handoff.md`.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import Counter
from pathlib import Path

from eval import common
from eval.meddocan import git_revision, load_documents


def _tokens(text: str) -> list:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _covered(tokens: list, spans: list) -> set:
    return {
        i for i, (s, e) in enumerate(tokens)
        if any(s < sp["end"] and sp["start"] < e for sp in spans)
    }


def _overlap(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip()).lower()
    return text.strip(".,;:()[]{}¿?¡!-_ ")


def _fp_source(span: dict, bert: list, regex: list) -> str:
    b = any(_overlap(span, x) for x in bert)
    r = [x for x in regex if _overlap(span, x)]
    if b and r:
        return "bert+regex"
    if b:
        return "bert"
    if r:
        return "regex:" + r[0]["label"]
    return "presidio"


def main() -> int:
    parser = argparse.ArgumentParser(description="Over-redaction metric")
    parser.add_argument("--corpus", default="data/meddocan/corpus")
    parser.add_argument("--split", default="test")
    parser.add_argument("--mode", choices=["combined", "presidio", "presidio_es"],
                        default="combined")
    parser.add_argument("--out", default="eval/results/over_redaction_test.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--breakdown", action="store_true",
                        help="Desglose diagnóstico por componente (solo dev)")
    parser.add_argument("--top-fp", type=int, default=30)
    args = parser.parse_args()

    docs = load_documents([args.split], Path(args.corpus))
    if not docs:
        print("[over-redaction] No hay documentos", file=sys.stderr)
        return 2

    if args.mode == "presidio":
        from src import presidio
        if not presidio.available():
            print("[over-redaction] Presidio no está disponible.", file=sys.stderr)
            return 2
    if args.mode == "presidio_es":
        from src import presidio
        if not presidio.available_es():
            print("[over-redaction] Presidio ES no está disponible.", file=sys.stderr)
            return 2

    predictor = common.Predictor(args.mode)

    over_tok = 0
    non_gold_tok = 0
    per_doc_over = []
    per_doc_non_gold = []
    by_source = Counter()
    fp_counts = Counter()
    fp_sources = {}

    for _name, text, gold in docs:
        pred = predictor.detect(text)
        tokens = _tokens(text)
        gold_tok = _covered(tokens, gold)
        pred_tok = _covered(tokens, pred)
        over = pred_tok - gold_tok
        nongold = set(range(len(tokens))) - gold_tok
        over_tok += len(over)
        non_gold_tok += len(nongold)
        per_doc_over.append(len(over))
        per_doc_non_gold.append(len(nongold))

        if not args.breakdown:
            continue

        if args.mode == "combined":
            bert = predictor._anon._bert_detect(text)  # noqa: SLF001
            regex = predictor._anon._regex_detect(text)  # noqa: SLF001
            bert_tok = _covered(tokens, bert)
            for i, (s, e) in enumerate(tokens):
                if i not in over:
                    continue
                rlabels = [x["label"] for x in regex
                           if s < x["end"] and x["start"] < e]
                b = i in bert_tok
                r = bool(rlabels)
                if b and r:
                    src = "bert+regex"
                elif b:
                    src = "bert"
                elif r:
                    src = "regex:" + rlabels[0]
                else:
                    src = "unattributed"
                by_source[src] += 1
            for p in pred:
                if any(_overlap(p, g) for g in gold):
                    continue
                norm = _normalize(p["text"])
                if not norm:
                    continue
                fp_counts[norm] += 1
                fp_sources.setdefault(norm, Counter())[_fp_source(p, bert, regex)] += 1
        else:
            by_source["presidio"] += len(over)
            for p in pred:
                if any(_overlap(p, g) for g in gold):
                    continue
                norm = _normalize(p["text"])
                if not norm:
                    continue
                fp_counts[norm] += 1
                fp_sources.setdefault(norm, Counter())["presidio"] += 1

    rate = round(over_tok / non_gold_tok, 4) if non_gold_tok else 0.0
    ci = common.bootstrap_ratio_ci(per_doc_over, per_doc_non_gold,
                                   n=args.bootstrap, seed=args.seed)

    result = {
        "script": "eval/over_redaction.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": git_revision(),
        "dirty": common.dirty(),
        "mode": args.mode,
        "split": args.split,
        "documents": len(docs),
        "seed": args.seed,
        "bootstrap": args.bootstrap,
        "per_doc": {"over_redacted": per_doc_over, "non_gold": per_doc_non_gold},
        "over_redaction": {
            "over_redacted_tokens": over_tok,
            "non_gold_tokens": non_gold_tok,
            "rate": rate,
            "ci95": [round(x, 4) for x in ci],
        },
        "notes": [
            "Over-redaction: non-PHI tokens (no overlap with any gold span) that "
            "fall inside a predicted span.",
            "Global rate with ratio bootstrap CI (resample docs, sum/sum; 95%, "
            "seed 42, 1000 resamples).",
        ],
    }
    if args.breakdown:
        result["breakdown"] = {
            "over_redacted_tokens": over_tok,
            "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
            "note": "Diagnostic only, computed on dev (not reportable).",
        }
        result["top_false_positives"] = [
            {"text": norm, "count": cnt,
             "source": fp_sources[norm].most_common(1)[0][0]}
            for norm, cnt in fp_counts.most_common(args.top_fp)
        ]
        result["notes"].append(
            "The per-component breakdown and top false positives are computed on "
            "dev because the frozen test predictions carry no provenance; dev is "
            "diagnostic, not reportable."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[over-redaction] {args.split} ({args.mode}): rate={rate:.4f} "
          f"({over_tok}/{non_gold_tok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Diagnóstico del detector sobre MEDDOCAN dev (Fase C).

Lee **solo** `dev`. No toca `test`. Produce `eval/results/diagnosis.json` con:

- matriz de confusión gold -> pred por clase (overlap),
- falsos negativos de NAME (top N, clasificados),
- sobre-redacción: % de tokens no-PHI alterados, por regla que los disparó.

Uso:

    python -m eval.diagnose --out eval/results/diagnosis.json

Las predicciones combinadas se cachean en `eval/results/.diagnosis_cache.jsonl`
para no recargar BERT en cada iteración.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from eval import common
from src import anonymizer

RULES = list(anonymizer.PATTERNS.keys()) + ["name_context", "name_discovery"]


def load_dev(corpus: Path):
    docs = []
    for ann_path in sorted((corpus / "dev" / "brat").glob("*.ann")):
        txt_path = ann_path.with_suffix(".txt")
        if txt_path.exists():
            text = common.read_text(txt_path)
            gold = common.gold_to_unified(common.parse_brat(ann_path))
            docs.append((ann_path.stem, text, gold))
    return docs


def _overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def _tokens(text):
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _tok_covered(tokens, spans):
    return {i for i, (s, e) in enumerate(tokens)
            if any(s < sp["end"] and sp["start"] < e for sp in spans)}


def confusion(gold, pred):
    """gold->pred confusion matrix (overlap, first match)."""
    rows = {}
    for g in gold:
        hit = None
        for p in pred:
            if _overlap(g, p):
                hit = p
                break
        gl = g["label"]
        pl = hit["label"] if hit else "(FN)"
        d = rows.setdefault(gl, {})
        d[pl] = d.get(pl, 0) + 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="data/meddocan/corpus")
    parser.add_argument("--out", default="eval/results/diagnosis.json")
    parser.add_argument("--cache", default="eval/results/.diagnosis_cache.jsonl")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    docs = load_dev(corpus)
    print(f"[diagnose] {len(docs)} documentos de dev")

    cache = Path(args.cache)
    cache_preds = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                cache_preds[o["id"]] = o["pred"]

    preds = {}
    need = [(i, n, t, g) for i, (n, t, g) in enumerate(docs) if n not in cache_preds]
    if need:
        predictor = common.Predictor("combined")
        with cache.open("a", encoding="utf-8") as fh:
            for i, n, t, _g in need:
                p = predictor.detect(t)
                preds[n] = p
                fh.write(json.dumps({"id": n, "pred": p}, ensure_ascii=False) + "\n")
                if (i + 1) % 25 == 0:
                    print(f"  ... {i + 1}/{len(need)}")
    for n in [d[0] for d in docs]:
        if n not in preds and n in cache_preds:
            preds[n] = cache_preds[n]

    # ── Confusión y FN de NAME ─────────────────────────────────────────
    conf = {}
    name_fn = []
    all_fp_tokens = 0
    all_nongold_tokens = 0
    for n, text, gold in docs:
        pred = preds.get(n, [])
        for g, row in confusion(gold, pred).items():
            c = conf.setdefault(g, {})
            for pl, cnt in row.items():
                c[pl] = c.get(pl, 0) + cnt
        # NAME false negatives
        for g in gold:
            if g["label"] == "NAME" and not any(_overlap(g, p) for p in pred):
                name_fn.append({"doc": n, "text": g["text"], "start": g["start"],
                                "end": g["end"]})
        # over-redaction overall (combined)
        tokens = _tokens(text)
        gold_tok = _tok_covered(tokens, gold)
        pred_tok = _tok_covered(tokens, pred)
        all_fp_tokens += len(pred_tok - gold_tok)
        all_nongold_tokens += len(tokens) - len(gold_tok)

    # ── Sobre-redacción por regla (regex-only, raw firing) ─────────────
    rule_fp_tokens = {}
    for _n, text, gold in docs:
        tokens = _tokens(text)
        gold_tok = _tok_covered(tokens, gold)
        for rule in anonymizer.PATTERNS:
            spans = [{"start": m.start(), "end": m.end()}
                     for m in anonymizer.PATTERNS[rule].finditer(text)]
            fp = _tok_covered(tokens, spans) - gold_tok
            rule_fp_tokens[rule] = rule_fp_tokens.get(rule, 0) + len(fp)

    result = {
        "script": "eval/diagnose.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": common_git(),
        "dirty": common.dirty(),
        "documents": len(docs),
        "confusion": conf,
        "name_false_negatives": name_fn,
        "over_redaction": {
            "fp_tokens_combined": all_fp_tokens,
            "non_gold_tokens": all_nongold_tokens,
            "rate": round(all_fp_tokens / all_nongold_tokens, 4)
            if all_nongold_tokens else 0.0,
        },
        "rule_fp_tokens": rule_fp_tokens,
        "notes": [
            "Confusión: por cada span gold, la clase de la primera predicción que se solapa.",
            "Sobre-redacción por regla: tokens NO-PHI cubiertos por cada regex (sin dedup).",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "confusion_ID": conf.get("ID"),
        "confusion_PHONE": conf.get("PHONE"),
        "over_redaction_rate": result["over_redaction"]["rate"],
        "name_fn_count": len(name_fn),
        "rule_fp_tokens": dict(sorted(rule_fp_tokens.items(),
                                      key=lambda kv: -kv[1])),
    }, indent=2, ensure_ascii=False))
    return 0


def common_git():
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())

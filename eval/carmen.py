"""CARMEN-I evaluation (secondary table, in-distribution upper bound).

CARMEN-I is not a headline metric: the model was fine-tuned on it and no public
train/test split is known. This script produces `eval/results/carmen_pukara.json`
for continuity with previously published figures and to show the size of the
in-distribution → out-of-distribution drop.

Run:  python -m eval.carmen --corpus data/carmen --out eval/results/carmen_pukara.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from eval import common
from eval.meddocan import _count, _div, _f1, _pr, git_revision


def load_carmen_docs(corpus: Path):
    docs = []
    ann_dir = corpus / "inputs" / "txt" / "ann"
    raw_dir = corpus / "inputs" / "txt" / "raw"
    if not ann_dir.exists():
        print(f"[carmen] Falta {ann_dir}", file=sys.stderr)
        return docs
    for ann_path in sorted(ann_dir.glob("*.ann")):
        txt_path = raw_dir / (ann_path.stem + ".txt")
        if not txt_path.exists():
            txt_path = ann_path.with_suffix(".txt")
        if not txt_path.exists():
            continue
        text = common.read_text(txt_path)
        gold = common.gold_to_unified(common.parse_brat(ann_path))
        docs.append((ann_path.stem, text, gold))
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description="CARMEN-I evaluation (secondary)")
    parser.add_argument("--corpus", default="data/carmen")
    parser.add_argument("--mode", choices=["regex", "bert", "combined"],
                        default="combined")
    parser.add_argument("--out", default="eval/results/carmen_pukara.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args()

    docs = load_carmen_docs(Path(args.corpus))
    if not docs:
        print("[carmen] No se encontraron documentos", file=sys.stderr)
        return 2

    predictor = common.Predictor(args.mode)

    word_tp = word_fp = word_fn = 0
    strict_tp = strict_fp = strict_fn = 0
    relaxed_tp = relaxed_fp = relaxed_fn = 0
    per_class_counts = {}
    leak_wide = leak_direct = leak_any = 0
    covered = total_gold = 0
    per_doc_word = []
    per_doc_relaxed = []
    per_doc_leak_wide = []
    per_doc_leak_direct = []
    per_doc_leak_any = []
    per_doc_neutr = []

    for idx, (_name, text, gold) in enumerate(docs):
        pred = predictor.detect(text)
        if (idx + 1) % 100 == 0:
            print(f"[carmen] {idx + 1}/{len(docs)}", flush=True)
        tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        gold_tok = {i for i, (s, e) in enumerate(tokens)
                    if any(s < g["end"] and g["start"] < e for g in gold)}
        pred_tok = {i for i, (s, e) in enumerate(tokens)
                    if any(s < p["end"] and p["start"] < e for p in pred)}
        wtp = len(gold_tok & pred_tok)
        wfp = len(pred_tok - gold_tok)
        wfn = len(gold_tok - pred_tok)
        word_tp += wtp
        word_fp += wfp
        word_fn += wfn

        tp, fp, fn = _count(common._span_exact, gold, pred)
        strict_tp += tp
        strict_fp += fp
        strict_fn += fn
        tp, fp, fn = _count(common._span_overlap, gold, pred)
        relaxed_tp += tp
        relaxed_fp += fp
        relaxed_fn += fn

        for lab in {g["label"] for g in gold} | {p["label"] for p in pred}:
            g = [x for x in gold if x["label"] == lab]
            p = [x for x in pred if x["label"] == lab]
            tp = 0
            matched = set()
            for gg in g:
                for pi, pp in enumerate(p):
                    if pi in matched:
                        continue
                    if common._span_exact(gg, pp):
                        tp += 1
                        matched.add(pi)
                        break
            c = per_class_counts.setdefault(lab, [0, 0, 0])
            c[0] += tp
            c[1] += len(p) - len(matched)
            c[2] += len(g) - tp

        lw = common.document_leakage_wide(gold, pred)
        ld = common.document_leakage(gold, pred)
        la = common.document_leakage_any(gold, pred)
        leak_wide += lw
        leak_direct += ld
        leak_any += la
        per_doc_leak_wide.append(1 if lw else 0)
        per_doc_leak_direct.append(1 if ld else 0)
        per_doc_leak_any.append(1 if la else 0)

        cov, tot = common.span_coverage(gold, pred)
        covered += cov
        total_gold += tot
        per_doc_neutr.append(cov / tot if tot else 0.0)

        per_doc_word.append(_f1(wtp, wfp, wfn))
        rtp, rfp, rfn = _count(common._span_overlap, gold, pred)
        per_doc_relaxed.append(_f1(rtp, rfp, rfn))

    word_p, word_r, word_f1 = _pr(word_tp, word_fp, word_fn)
    strict_p, strict_r, strict_f1 = _pr(strict_tp, strict_fp, strict_fn)
    relaxed_p, relaxed_r, relaxed_f1 = _pr(relaxed_tp, relaxed_fp, relaxed_fn)

    per_class = {}
    for lab, (tp, fp, fn) in sorted(per_class_counts.items()):
        per_class[lab] = {
            "precision": _div(tp, tp + fp),
            "recall": _div(tp, tp + fn),
            "f1": _div(2 * tp, 2 * tp + fp + fn),
            "support": tp + fn,
        }

    result = {
        "script": "eval/carmen.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": git_revision(),
        "mode": args.mode,
        "model": common.MODEL_META,
        "seed": args.seed,
        "documents": len(docs),
        "word_level": {
            "precision": round(word_p, 4),
            "recall": round(word_r, 4),
            "f1": round(word_f1, 4),
            "f1_ci95": [round(x, 4) for x in
                        common.bootstrap_ci(per_doc_word, n=args.bootstrap, seed=args.seed)],
        },
        "span_strict": {
            "precision": round(strict_p, 4),
            "recall": round(strict_r, 4),
            "f1": round(strict_f1, 4),
        },
        "span_relaxed": {
            "precision": round(relaxed_p, 4),
            "recall": round(relaxed_r, 4),
            "f1": round(relaxed_f1, 4),
            "f1_ci95": [round(x, 4) for x in
                        common.bootstrap_ci(per_doc_relaxed, n=args.bootstrap, seed=args.seed)],
        },
        "per_class": per_class,
        "phi_neutralization": {
            "covered_spans": covered,
            "total_spans": total_gold,
            "rate": round(covered / total_gold, 4) if total_gold else 0.0,
            "ci95": [round(x, 4) for x in
                     common.bootstrap_ci(per_doc_neutr, n=args.bootstrap, seed=args.seed)],
        },
        "leakage": {
            "wide": {"leaked_docs": leak_wide, "total_docs": len(docs),
                     "rate": round(leak_wide / len(docs), 4),
                     "ci95": [round(x, 4) for x in common.bootstrap_ci(
                         per_doc_leak_wide, n=args.bootstrap, seed=args.seed)]},
            "direct": {"leaked_docs": leak_direct, "total_docs": len(docs),
                       "rate": round(leak_direct / len(docs), 4),
                       "ci95": [round(x, 4) for x in common.bootstrap_ci(
                           per_doc_leak_direct, n=args.bootstrap, seed=args.seed)]},
            "any_phi": {"leaked_docs": leak_any, "total_docs": len(docs),
                        "rate": round(leak_any / len(docs), 4),
                        "ci95": [round(x, 4) for x in common.bootstrap_ci(
                            per_doc_leak_any, n=args.bootstrap, seed=args.seed)]},
        },
        "note": "Pukara: the BERT model is fine-tuned on CARMEN-I; in-distribution, "
                "possible train overlap, upper bound.",
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[carmen] {len(docs)} documentos. Word F1={word_f1:.4f}, "
          f"Neutralización={result['phi_neutralization']['rate']:.4f}, "
          f"Leakage(wide)={result['leakage']['wide']['rate']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""MEDDOCAN intrinsic evaluation (Phase 4.1).

Run from the repo root:

    python -m eval.meddocan --corpus data/meddocan/corpus --mode regex \
        --out eval/results/meddocan.json

`--mode bert` and `--mode combined` require the gated model
`BSC-NLP4BIA/bsc-bio-ehr-es-carmen-anon` under `models/` (or `--model-dir`).
Until then the harness fails with a clear message and writes no numbers.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

from eval import common


def git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def load_documents(splits: list[str], corpus: Path):
    docs = []
    for split in splits:
        ann_dir = corpus / split / "brat"
        if not ann_dir.exists():
            print(f"[eval] Falta el split {split} en {ann_dir}", file=sys.stderr)
            sys.exit(2)
        for ann_path in sorted(ann_dir.glob("*.ann")):
            txt_path = ann_path.with_suffix(".txt")
            if not txt_path.exists():
                continue
            text = common.read_text(txt_path)
            gold = common.gold_to_unified(common.parse_brat(ann_path))
            docs.append((ann_path.stem, text, gold))
    return docs


def main() -> int:
    parser = argparse.ArgumentParser(description="MEDDOCAN intrinsic evaluation")
    parser.add_argument("--corpus", default="data/meddocan/corpus")
    parser.add_argument("--split", default="dev,test")
    parser.add_argument("--mode", choices=["regex", "bert", "combined", "presidio"],
                        default="combined")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--out", default="eval/results/meddocan.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--presidio", action="store_true",
                        help="Activar Presidio en modo combined (extra opcional)")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    splits = [s.strip() for s in args.split.split(",") if s.strip()]

    docs = load_documents(splits, corpus)
    if not docs:
        print(f"[eval] No se encontraron documentos en {corpus}", file=sys.stderr)
        return 2

    if args.mode in ("bert", "combined"):
        model_dir = Path(args.model_dir) if args.model_dir else (common.ROOT / "models")
        if not (model_dir / "bsc-bio-ehr-es-carmen-anon").exists():
            print(f"[eval] El modelo BERT no está disponible en {model_dir}.",
                  file=sys.stderr)
            return 2
    if args.mode == "presidio":
        from src import presidio
        if not presidio.available():
            print("[eval] Presidio no está disponible (spaCy es_core_news_lg).",
                  file=sys.stderr)
            return 2
    predictor = common.Predictor(args.mode, args.model_dir,
                                 use_presidio=args.presidio)

    per_doc = []
    per_doc_relaxed = []
    leak_wide_count = 0
    leak_direct_count = 0
    leak_any_count = 0
    per_doc_leak_wide = []
    per_doc_leak_direct = []
    per_doc_leak_any = []
    per_doc_neutr = []
    covered_spans = 0
    total_gold_spans = 0
    # Aggregated counts.
    word_tp = word_fp = word_fn = 0
    strict_tp = strict_fp = strict_fn = 0
    relaxed_tp = relaxed_fp = relaxed_fn = 0
    per_class_counts = {}  # label -> [tp, fp, fn]

    for _name, text, gold in docs:
        pred = predictor.detect(text)
        # Word level (binary PHI over whitespace tokens).
        tokens = [(m.start(), m.end()) for m in __import__("re").finditer(r"\S+", text)]
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

        # Span level.
        tp, fp, fn = _count(common._span_exact, gold, pred)
        strict_tp += tp
        strict_fp += fp
        strict_fn += fn
        tp, fp, fn = _count(common._span_overlap, gold, pred)
        relaxed_tp += tp
        relaxed_fp += fp
        relaxed_fn += fn

        # Per-class.
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

        if common.document_leakage_wide(gold, pred):
            leak_wide_count += 1
        if common.document_leakage(gold, pred):
            leak_direct_count += 1
        if common.document_leakage_any(gold, pred):
            leak_any_count += 1
        per_doc_leak_wide.append(1 if common.document_leakage_wide(gold, pred) else 0)
        per_doc_leak_direct.append(1 if common.document_leakage(gold, pred) else 0)
        per_doc_leak_any.append(1 if common.document_leakage_any(gold, pred) else 0)
        cov, tot = common.span_coverage(gold, pred)
        covered_spans += cov
        total_gold_spans += tot
        per_doc_neutr.append(cov / tot if tot else 0.0)

        # Per-doc F1 values for bootstrap CIs.
        per_doc.append(_f1(wtp, wfp, wfn))
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

    word_ci = common.bootstrap_ci(per_doc, n=args.bootstrap, seed=args.seed)
    relaxed_ci = common.bootstrap_ci(per_doc_relaxed, n=args.bootstrap, seed=args.seed)
    neutr_ci = common.bootstrap_ci(per_doc_neutr, n=args.bootstrap, seed=args.seed)
    wide_ci = common.bootstrap_ci(per_doc_leak_wide, n=args.bootstrap, seed=args.seed)
    direct_ci = common.bootstrap_ci(per_doc_leak_direct, n=args.bootstrap, seed=args.seed)
    any_ci = common.bootstrap_ci(per_doc_leak_any, n=args.bootstrap, seed=args.seed)

    presidio_meta = None
    if args.mode == "presidio":
        presidio_meta = common.presidio_meta([t for _, t, _g in docs])

    result = {
        "script": "eval/meddocan.py",
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "code_revision": git_revision(),
        "dirty": common.dirty(),
        "mode": args.mode,
        "presidio": (args.mode == "combined" and args.presidio),
        "presidio_meta": presidio_meta,
        "model": common.MODEL_META if args.mode in ("bert", "combined") else None,
        "seed": args.seed,
        "splits": splits,
        "documents": len(docs),
        "word_level": {
            "precision": round(word_p, 4),
            "recall": round(word_r, 4),
            "f1": round(word_f1, 4),
            "f1_ci95": [round(x, 4) for x in word_ci],
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
            "f1_ci95": [round(x, 4) for x in relaxed_ci],
        },
        "per_class": per_class,
        "phi_neutralization": {
            "covered_spans": covered_spans,
            "total_spans": total_gold_spans,
            "rate": round(covered_spans / total_gold_spans, 4)
            if total_gold_spans else 0.0,
            "ci95": [round(x, 4) for x in neutr_ci],
        },
        "leakage": {
            "wide": {
                "leaked_docs": leak_wide_count,
                "total_docs": len(docs),
                "rate": round(leak_wide_count / len(docs), 4) if len(docs) else 0.0,
                "ci95": [round(x, 4) for x in wide_ci],
            },
            "direct": {
                "leaked_docs": leak_direct_count,
                "total_docs": len(docs),
                "rate": round(leak_direct_count / len(docs), 4) if len(docs) else 0.0,
                "ci95": [round(x, 4) for x in direct_ci],
            },
            "any_phi": {
                "leaked_docs": leak_any_count,
                "total_docs": len(docs),
                "rate": round(leak_any_count / len(docs), 4) if len(docs) else 0.0,
                "ci95": [round(x, 4) for x in any_ci],
            },
        },
        "notes": [
            "Gold and predictions are unified-label PHI spans.",
            "Leakage wide (principal): EMAIL, FAMILY, NAME, ID, PHONE, URL, PROFESSIONAL.",
            "Leakage direct: EMAIL, NAME, PHONE, ID.",
            "Leakage any_phi: any gold PHI span missed (label-agnostic).",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(
        f"[eval] {len(docs)} documentos ({args.mode}). Word F1={word_f1:.4f}, "
        f"Neutralización={result['phi_neutralization']['rate']:.4f}, "
        f"Leakage(any PHI)={result['leakage']['any_phi']['rate']:.4f}"
    )
    return 0


def _count(matcher, gold, pred):
    matched_gold = set()
    matched_pred = set()
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            if pi in matched_pred:
                continue
            if matcher(g, p):
                matched_gold.add(gi)
                matched_pred.add(pi)
                break
    return (
        len(matched_gold),
        len(pred) - len(matched_pred),
        len(gold) - len(matched_gold),
    )


def _div(a, b):
    return a / b if b else 0.0


def _f1(tp, fp, fn):
    p = _div(tp, tp + fp)
    r = _div(tp, tp + fn)
    return _div(2 * p * r, p + r)


def _pr(tp, fp, fn):
    p = _div(tp, tp + fp)
    r = _div(tp, tp + fn)
    f1 = _div(2 * p * r, p + r)
    return p, r, f1


if __name__ == "__main__":
    sys.exit(main())
